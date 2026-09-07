"""Опасности голоса фоновой уборки истории (Task 3.8, пункт «в»).

Авторский набор, дополняющий независимый приёмочный
(``test_f3_task38_history_purge_voice_acceptance.py``). Он проверяет не критерии
приёмки, а устройство механизма — то, чего слепой тестер увидеть не мог, потому
что не знал про таблицу ``_SAY_FALLBACKS`` и про расположение голоса относительно
``try`` вокруг ``purge``.

Главная опасность здесь одна и она неочевидна: **у уровня DEBUG в этом модуле есть
запасная лесенка, и если дать ей подниматься вверх, понижение уровня отменяется
само собой** — процесс без debug-логгера начнёт кричать болтовню на INFO. Такой
дефект зелёный на всех приёмочных тестах, потому что у их двойника debug-логгер
есть.
"""

from __future__ import annotations

from typing import Any, List, Optional

import pytest

from multiprocess_framework.modules.process_module.managers.observability_wiring import (
    _SAY_FALLBACKS,
    sweep_observability_history,
)


class _Store:
    """Стор-двойник: отдаёт заранее назначенный отчёт либо роняет исключение."""

    def __init__(self, report: Any = None, *, raises: Optional[BaseException] = None) -> None:
        self._report = report
        self._raises = raises
        self.calls = 0

    def purge(self, *, max_rows: Any = None, max_age_sec: Any = None) -> Any:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return self._report


class _SvcWithoutDebugLogger:
    """Процесс, у которого debug-логгера НЕТ — только info и warning.

    Ровно та конфигурация, на которой лесенка DEBUG→INFO выстрелила бы: болтовня
    полезла бы в INFO, и понижение уровня оказалось бы декоративным.
    """

    def __init__(self, store: Any) -> None:
        self._observability_store = store
        self._observability_history_policy = {"max_rows": 10, "max_age_sec": 60.0, "purge_interval_sec": 0.0}
        self.info_messages: List[str] = []
        self.warning_messages: List[str] = []

    def log_info(self, message: str, module: str = "") -> None:
        self.info_messages.append(message)

    def log_warning(self, message: str, module: str = "") -> None:
        self.warning_messages.append(message)


class _SvcWithDebugLogger(_SvcWithoutDebugLogger):
    def __init__(self, store: Any) -> None:
        super().__init__(store)
        self.debug_messages: List[str] = []

    def log_debug(self, message: str, module: str = "") -> None:
        self.debug_messages.append(message)


class _SvcWhoseLoggerExplodes(_SvcWithDebugLogger):
    """Логгер, который роняет НЕ TypeError — то есть не «логгер без kwarg module»."""

    def log_info(self, message: str, module: str = "") -> None:
        raise RuntimeError("логгер сломан")

    def log_debug(self, message: str, module: str = "") -> None:
        raise RuntimeError("логгер сломан")


class TestDebugLadderDoesNotClimbToInfo:
    """Понижение уровня обязано пережить отсутствие debug-логгера."""

    def test_zero_sweep_on_a_process_without_debug_logger_says_nothing_at_all(self) -> None:
        """Нет debug-логгера — строки нет; на INFO болтовня НЕ поднимается.

        Это и есть сознательное исключение из «молчание недопустимо ни при каком»:
        поднявшись до INFO, строка «снято 0» вернула бы 96 записей в час на восьми
        процессах — то, ради чего уровень и понижали.
        """
        svc = _SvcWithoutDebugLogger(_Store({"by_age": 0, "by_rows": 0, "remaining": 7}))

        report = sweep_observability_history(svc)

        assert report == {"by_age": 0, "by_rows": 0, "remaining": 7}
        assert svc.info_messages == []
        assert svc.warning_messages == []

    def test_non_zero_sweep_on_the_same_process_still_reaches_info(self) -> None:
        """Контроль к предыдущему: молчит именно болтовня, а не механизм целиком.

        Без этой пары первый тест был бы зелёным и на голосе, удалённом вовсе.
        """
        svc = _SvcWithoutDebugLogger(_Store({"by_age": 4, "by_rows": 3, "remaining": 11}))

        sweep_observability_history(svc)

        assert len(svc.info_messages) == 1
        assert "7" in svc.info_messages[0]
        assert svc.warning_messages == []

    def test_debug_ladder_is_declared_and_does_not_mention_info_rungs(self) -> None:
        """Литерал таблицы, а не поведение: свойство обязано быть видно в объявлении.

        Поведенческие тесты выше зависят от того, какие логгеры есть у двойника;
        этот стережёт саму лесенку, чтобы «починка» таблицы не прошла молча.
        """
        assert "DEBUG" in _SAY_FALLBACKS, "process_say(..., 'DEBUG') ушёл бы по WARNING-лесенке"
        assert _SAY_FALLBACKS["DEBUG"] == ("_log_debug", "log_debug")


class TestVoiceDoesNotLieAboutItsNeighbour:
    """Отказ голоса не имеет права выглядеть отказом уборки."""

    def test_a_broken_logger_does_not_produce_the_purge_failed_warning(self) -> None:
        """Голос стоит ЗА пределами try вокруг purge — проверяем это наблюдаемо.

        Если голос уедет внутрь try, RuntimeError логгера будет доложен как
        «уборка истории не удалась», и оператор пойдёт чинить БД вместо логгера.
        """
        store = _Store({"by_age": 1, "by_rows": 0, "remaining": 2})
        svc = _SvcWhoseLoggerExplodes(store)

        with pytest.raises(RuntimeError):
            sweep_observability_history(svc)

        assert store.calls == 1, "уборка обязана была отработать ДО падения голоса"
        assert svc.warning_messages == [], "отказ голоса доложен как отказ уборки — механизм врёт о соседе"


class TestReportShapeIsNotAssumed:
    """Голос читает отчёт, но не обязан верить, что он словарь нужной формы."""

    @pytest.mark.parametrize("odd_report", [None, "не словарь", 42, []])
    def test_a_non_dict_report_is_returned_untouched_and_voices_nothing(self, odd_report: Any) -> None:
        svc = _SvcWithDebugLogger(_Store(odd_report))

        report = sweep_observability_history(svc)

        assert report is odd_report or report == odd_report
        assert svc.info_messages == []
        assert svc.debug_messages == []

    def test_missing_keys_are_read_as_zero_rather_than_crashing_the_tick(self) -> None:
        """Отчёт без ключей — не повод ронять такт heartbeat."""
        svc = _SvcWithDebugLogger(_Store({}))

        report = sweep_observability_history(svc)

        assert report == {}
        assert svc.info_messages == []
        assert len(svc.debug_messages) == 1
        assert "0" in svc.debug_messages[0]

    def test_none_valued_keys_are_read_as_zero(self) -> None:
        """``{"by_age": None}`` не должен превращаться в TypeError внутри такта."""
        svc = _SvcWithDebugLogger(_Store({"by_age": None, "by_rows": None, "remaining": None}))

        report = sweep_observability_history(svc)

        assert report == {"by_age": None, "by_rows": None, "remaining": None}
        assert len(svc.debug_messages) == 1


class TestNumbersInTheLineAreTheOnesThatHappened:
    """Строка обязана нести числа отчёта, а не пересчитывать их по-своему."""

    def test_partial_sweep_names_both_halves_including_the_zero_one(self) -> None:
        """Срез только по числу строк: ноль по возрасту всё равно назван.

        Открытый вопрос независимого тестера — он этого не проверял. Опустив
        нулевое слагаемое, реализация заставила бы читателя гадать, какая из двух
        мер сработала.
        """
        svc = _SvcWithDebugLogger(_Store({"by_age": 0, "by_rows": 25, "remaining": 100}))

        sweep_observability_history(svc)

        assert len(svc.info_messages) == 1
        line = svc.info_messages[0]
        assert "25" in line
        assert "0" in line
        assert "100" in line
