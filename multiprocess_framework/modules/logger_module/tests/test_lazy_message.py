# -*- coding: utf-8 -*-
"""Ф1.4-1.5 — цена сообщения платится только за принятую запись.

Заявленные свойства и как каждое ломается отдельно:

  1.4a  ``Callable`` не вызывается при закрытом гейте;
  1.4b  ``Callable`` вызывается РОВНО ОДИН раз, сколько бы каналов ни было;
  1.4c  ``%``-формат применяется один раз и тоже после гейта;
  1.5   ``StdLoggerFacade`` не склеивает строку до гейта — то есть ``__str__``
        аргументов не выполняется на отклонённой записи.

Все счётчики — на САМОМ аргументе (``__str__``, вызов lambda), а не на шпионе
за именем метода: шпион за ``apply_format`` сторожил бы имя функции, а не
свойство «дорогое не вычисляется». Это прямой урок ревью фазы Ф0 про тест,
следивший за ``Path.rglob``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.logger_module.adapters import std_facade
from multiprocess_framework.modules.logger_module.adapters.std_facade import StdLoggerFacade
from multiprocess_framework.modules.logger_module.core.log_config import LogLevel, LogScope
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager


class _CountingArg:
    """Аргумент, который считает, сколько раз его превращали в строку."""

    def __init__(self, value: str = "значение") -> None:
        self.value = value
        self.str_calls = 0

    def __str__(self) -> str:
        self.str_calls += 1
        return self.value

    __repr__ = __str__


def _manager(tmp_path: Path, **overrides: Any) -> LoggerManager:
    config: Dict[str, Any] = {
        "app_name": "lazy",
        "log_directory": str(tmp_path),
        "enable_batching": False,
        "modules": {},
        "channels": {
            "a": {"type": "file", "enabled": True, "file_path": str(tmp_path / "a.log")},
            "b": {"type": "file", "enabled": True, "file_path": str(tmp_path / "b.log")},
        },
        "scopes": {
            "BUSINESS": {"channels": ["a", "b"]},
            "SYSTEM": {"channels": ["a"]},
            "DEBUG": {"channels": ["a"]},
        },
    }
    config.update(overrides)
    mgr = LoggerManager(manager_name="LazyProbe", config=config)
    mgr.initialize()
    return mgr


@pytest.fixture
def logger(tmp_path: Path):
    mgr = _manager(tmp_path)
    yield mgr
    mgr.shutdown()


class TestCallableMessage:
    def test_not_called_when_gate_closed(self, logger: LoggerManager) -> None:
        """1.4a — выключенный DEBUG-скоуп не платит за сборку сообщения."""
        calls: List[int] = []

        logger.debug(lambda: calls.append(1) or "дорогая строка", module="probe")

        assert calls == [], "сообщение вычислено, хотя запись отклонена гейтом"
        assert logger.get_stats()["messages_skipped"] >= 1

    def test_called_once_regardless_of_channel_count(self, logger: LoggerManager) -> None:
        """1.4b — два канала, но одно вычисление.

        Проверяется именно на скоупе с ДВУМЯ приёмниками: реализация, собирающая
        сообщение внутри цикла по каналам, здесь и умирает.
        """
        calls: List[int] = []

        logger.info(lambda: calls.append(1) or "однажды", module="probe")

        assert len(calls) == 1
        assert logger._route(LogScope.BUSINESS, LogLevel.INFO, "probe") == ["a", "b"], (
            "предусловие теста: приёмников должно быть больше одного"
        )

    def test_result_reaches_the_channel(self, logger: LoggerManager, tmp_path: Path) -> None:
        logger.info(lambda: "текст из callable", module="probe")
        logger.flush()
        assert "текст из callable" in (tmp_path / "a.log").read_text(encoding="utf-8")


class TestMessageBuildFailure:
    """Hazard самого механизма Ф1.4: дорогая сборка — это то, что умеет падать.

    Авторские тесты на механизм, а не на контракт: смысл фичи — перенести
    сборку сообщения ВНУТРЬ логгера, значит внутрь логгера переехало и её
    падение. Первая редакция не ловила его вовсе, и исключение пробивалось в
    вызывающий код — приложение падало на строчке логирования (найдено второй
    итерацией ревью Ф1). Политика взята у соседнего пути ``apply_format``:
    запись сохраняется, факт считается.
    """

    def test_raising_callable_does_not_escape(self, logger: LoggerManager) -> None:
        def _boom() -> str:
            raise RuntimeError("сборка упала")

        before = logger.get_stats()["message_build_failures"]
        logger.info(_boom, module="probe")  # НЕ должно бросить
        after = logger.get_stats()

        assert after["message_build_failures"] == before + 1
        assert after["messages_skipped"] == logger.get_stats()["messages_skipped"]

    def test_record_survives_with_a_visible_marker(self, logger: LoggerManager, tmp_path: Path) -> None:
        """Запись не теряется: вместо текста — видимый след сбоя, а не тишина."""

        def _boom() -> str:
            raise RuntimeError("нет данных для строки")

        logger.info(_boom, module="probe")
        logger.flush()

        text = (tmp_path / "a.log").read_text(encoding="utf-8")
        assert "сборка сообщения упала" in text
        assert "нет данных для строки" in text, "причина сбоя обязана попасть в запись"

    def test_broken_str_on_non_callable_is_handled_too(self, logger: LoggerManager) -> None:
        """Не-строка с падающим ``__str__`` — та же ветка, та же политика."""

        class _Bad:
            def __str__(self) -> str:
                raise ValueError("__str__ упал")

        before = logger.get_stats()["message_build_failures"]
        logger.info(_Bad(), module="probe")

        assert logger.get_stats()["message_build_failures"] == before + 1

    def test_closed_gate_never_reaches_the_failure(self, logger: LoggerManager) -> None:
        """Падающий callable при закрытом гейте не зовётся — счётчик молчит."""

        def _boom() -> str:
            raise RuntimeError("не должно быть вызвано")

        before = logger.get_stats()["message_build_failures"]
        logger.debug(_boom, module="probe")

        assert logger.get_stats()["message_build_failures"] == before

    def test_healthy_path_leaves_the_counter_at_zero(self, logger: LoggerManager) -> None:
        """Страж от счётчика, который «работает» на всём подряд."""
        logger.info(lambda: "нормальная строка", module="probe")
        logger.info("обычная строка", module="probe")

        assert logger.get_stats()["message_build_failures"] == 0


class TestPercentArgs:
    def test_not_formatted_when_gate_closed(self, logger: LoggerManager) -> None:
        """1.4c — аргументы не приводятся к строке на отклонённой записи."""
        arg = _CountingArg()

        logger.debug("значение: %s", "probe", arg)

        assert arg.str_calls == 0, "аргумент отформатирован, хотя запись отклонена"

    def test_formatted_once_for_two_channels(self, logger: LoggerManager) -> None:
        arg = _CountingArg()

        logger.info("значение: %s", "probe", arg)

        assert arg.str_calls == 1

    def test_formatted_text_on_disk(self, logger: LoggerManager, tmp_path: Path) -> None:
        logger.info("процесс '%s' код %d", "probe", "pult", 42)
        logger.flush()
        assert "процесс 'pult' код 42" in (tmp_path / "a.log").read_text(encoding="utf-8")

    def test_broken_format_keeps_message_and_args(self, logger: LoggerManager, tmp_path: Path) -> None:
        """Кривой шаблон не имеет права съесть запись — правило пережило переезд."""
        logger.info("без плейсхолдеров", "probe", "лишний")
        logger.flush()
        text = (tmp_path / "a.log").read_text(encoding="utf-8")
        assert "без плейсхолдеров" in text and "лишний" in text

    def test_module_stays_positional(self, logger: LoggerManager, tmp_path: Path) -> None:
        """Четвёртый позиционный аргумент — по-прежнему ``module``, а не формат.

        Совместимость: во фреймворке сотни вызовов вида
        ``log(scope, level, msg, "имя_модуля")``. Если бы ``*args`` встали
        раньше, имя модуля молча уехало бы в аргументы формата.
        """
        logger.log(LogScope.BUSINESS, LogLevel.INFO, "позиционный модуль", "probe")
        logger.flush()
        assert "probe" in (tmp_path / "a.log").read_text(encoding="utf-8")


class TestStdFacadeGatesBeforeFormatting:
    """1.5 — фасад отдаёт шаблон менеджеру, а не готовую строку."""

    def test_rejected_record_costs_no_formatting(self, logger: LoggerManager, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(std_facade, "get_logger", lambda: logger)
        arg = _CountingArg()

        # debug → LogScope.DEBUG, выключен в конфиге фикстуры.
        assert StdLoggerFacade("probe").debug("дорогое: %s", arg) is True

        assert arg.str_calls == 0, "фасад склеил строку до гейта — Ф1.5 не работает"

    def test_accepted_record_is_formatted_exactly_once(
        self, logger: LoggerManager, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(std_facade, "get_logger", lambda: logger)
        arg = _CountingArg("готово")

        StdLoggerFacade("probe").info("итог: %s", arg)
        logger.flush()

        assert arg.str_calls == 1
        assert "итог: готово" in (tmp_path / "a.log").read_text(encoding="utf-8")

    def test_module_still_reaches_manager(
        self, logger: LoggerManager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Имя модуля доезжает ДО ФАЙЛА, а аргументы склеиваются в менеджере.

        Прежняя редакция ставила спай на ``logger.info`` — то есть сторожила
        ИМЯ метода, а не свойство. 2.2 перевела вид на прямой ``log()``, и спай
        замолчал, хотя имя модуля продолжало доезжать: тест «поймал» смену
        внутреннего пути и не заметил бы настоящей потери имени, случись она
        на другом маршруте. Правило проекта ровно об этом: утверждать надо
        наблюдаемый эффект — байты в файле.
        """
        monkeypatch.setattr(std_facade, "get_logger", lambda: logger)

        StdLoggerFacade("trace_probe").info("x=%s", 1)
        logger.flush()

        line = (tmp_path / "a.log").read_text(encoding="utf-8").splitlines()[-1]
        assert "trace_probe" in line, f"имя модуля не доехало до файла: {line!r}"
        assert "x=1" in line, f"аргументы не склеились в менеджере: {line!r}"
        assert "%s" not in line, f"шаблон остался несклеенным: {line!r}"

    def test_fallback_without_manager_still_formats(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Без менеджера фасад форматирует сам — иначе stdlib получил бы шаблон."""
        monkeypatch.setattr(std_facade, "get_logger", lambda: None)
        with caplog.at_level("WARNING"):
            assert StdLoggerFacade("probe").warning("код %d", 7) is False
        assert "код 7" in caplog.text
