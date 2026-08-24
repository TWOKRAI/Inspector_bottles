# -*- coding: utf-8 -*-
"""Task Т.1 — тесты АВТОРА на опасности самого механизма ``_call_manager``.

Дополнение к независимому набору ``test_manager_call_failure_visibility.py``,
а не замена: тот пишется по критериям приёмки и сторожит контракт снаружи,
этот — внутренние грабли, видные только тому, кто знает, как ветка устроена.

Три опасности, ради которых файл существует:

1. **Два рода отказа не должны слипнуться в один текст.** «Менеджер бросил» и
   «у менеджера нет метода» лежат в ОДНОМ счётчике (это сознательно — обе
   означают «запись потеряна»), но чинятся по-разному: первое — приёмник,
   второе — проводка. Если WARNING перестанет их различать, читатель лога
   пойдёт чинить не то.
2. **Ложный «нет метода» на вызываемом объекте с ложным ``__bool__``.** Старое
   условие ``if method and callable(method)`` пропускало такой объект мимо
   вызова МОЛЧА; после Т.1 оно бы ещё и посчитало отказ, которого нет.
   Поэтому в коде стоит ``method is not None``, и это надо сторожить.
3. **Цена успешного пути.** ``_call_manager`` стоит на hot-path каждого лога и
   каждой метрики. Успех не имеет права ни аллоцировать словарь счётчиков, ни
   делать лишний lookup.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from ..core.base_manager import BaseManager
from ..mixins.observable_mixin import ObservableMixin

_MODULE_LOGGER_NAME = "multiprocess_framework.modules.base_manager.mixins.observable_mixin"


class _Probe(BaseManager, ObservableMixin):
    __test__ = False

    def __init__(self, name: str, logger: Any = None) -> None:
        BaseManager.__init__(self, name)
        managers: dict[str, Any] = {"logger": logger} if logger is not None else {}
        ObservableMixin.__init__(self, managers=managers, config={k: True for k in managers})

    def initialize(self) -> bool:
        self.is_initialized = True
        return True

    def shutdown(self) -> bool:
        self.is_initialized = False
        return True


class _NoWarning:
    """Метода warning нет вовсе."""

    def info(self, msg: str, **kwargs: Any) -> None:
        pass


class _RaisingWarning:
    """Метод warning есть, но бросает."""

    def warning(self, msg: str, **kwargs: Any) -> None:
        raise RuntimeError("сломанный sink")


class _FalsyCallable:
    """Вызываемый объект, у которого ``bool(obj)`` — False.

    Ровно та ловушка, из-за которой в ``_call_manager`` стоит ``is not None``,
    а не проверка на истинность.
    """

    def __init__(self) -> None:
        self.seen: list[str] = []

    def __len__(self) -> int:  # bool(self) == False
        return 0

    def __call__(self, msg: str, **kwargs: Any) -> str:
        self.seen.append(msg)
        return "вызван"


class _WarningIsNotCallable:
    """Атрибут ``warning`` есть, но это не метод — вызвать нечем."""

    warning = "строка, а не функция"


class TestTwoKindsOfFailureAreDistinguishable:
    """Опасность 1: тексты WARNING обязаны разводить причины."""

    def test_missing_method_warning_names_the_wiring_defect_and_the_manager_type(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        probe = _Probe("probe", logger=_NoWarning())

        with caplog.at_level(logging.WARNING, logger=_MODULE_LOGGER_NAME):
            probe._log_warning("нет метода")

        text = caplog.records[0].getMessage()
        assert "logger.warning" in text
        assert "нет вызываемого метода" in text, text
        # Тип объекта в слоте — единственная подсказка, ЧТО подали не туда.
        assert "_NoWarning" in text, text

    def test_raising_method_warning_names_the_exception_not_the_wiring(self, caplog: pytest.LogCaptureFixture) -> None:
        probe = _Probe("probe", logger=_RaisingWarning())

        with caplog.at_level(logging.WARNING, logger=_MODULE_LOGGER_NAME):
            probe._log_warning("бах")

        text = caplog.records[0].getMessage()
        assert "logger.warning" in text
        assert "RuntimeError" in text, text
        assert "сломанный sink" in text, text
        # И НЕ должен обвинять проводку — метод-то на месте.
        assert "нет вызываемого метода" not in text, text

    def test_the_two_texts_are_actually_different(self, caplog: pytest.LogCaptureFixture) -> None:
        """Оракул против вакуума: если оба текста совпадут, тесты выше пройдут
        только на подстроках, а различить причины будет нельзя."""
        with caplog.at_level(logging.WARNING, logger=_MODULE_LOGGER_NAME):
            _Probe("a", logger=_NoWarning())._log_warning("x")
            _Probe("b", logger=_RaisingWarning())._log_warning("x")

        missing, raising = (r.getMessage() for r in caplog.records[:2])
        assert missing != raising

    def test_non_callable_attribute_counts_as_missing_not_as_success(self) -> None:
        """``warning`` есть как атрибут, но вызвать нечего — это тот же дефект
        проводки, а не успех и не исключение."""
        probe = _Probe("probe", logger=_WarningIsNotCallable())

        probe._log_warning("строка вместо метода")

        assert probe.manager_call_failures == {"logger.warning": 1}


class TestFalsyCallableIsNotAFailure:
    """Опасность 2: вызываемый объект с ложным __bool__ обязан быть ВЫЗВАН."""

    def test_falsy_callable_method_is_invoked_and_not_counted(self) -> None:
        logger = type("L", (), {})()
        falsy = _FalsyCallable()
        logger.warning = falsy  # type: ignore[attr-defined]
        probe = _Probe("probe", logger=logger)

        result = probe._call_manager("logger", "warning", "полезная запись")

        assert result == "вызван", "вызываемый объект с ложным __bool__ не был вызван"
        assert falsy.seen == ["полезная запись"]
        assert probe.manager_call_failures == {}, (
            "успешный вызов посчитан отказом — вернулась проверка на истинность "
            f"вместо `is not None`: {probe.manager_call_failures!r}"
        )


class TestSuccessPathCostsNothing:
    """Опасность 3: успех не платит за учёт отказов."""

    def test_success_does_not_even_allocate_the_failures_dict(self) -> None:
        class _Full:
            def warning(self, msg: str, **kwargs: Any) -> None:
                pass

        probe = _Probe("probe", logger=_Full())

        for _ in range(100):
            probe._log_warning("горячий путь")

        assert "_manager_call_failures" not in probe.__dict__, (
            "успешный путь создал словарь счётчиков — учёт протёк в hot-path"
        )

    def test_counter_dict_appears_only_on_the_first_failure(self) -> None:
        probe = _Probe("probe", logger=_NoWarning())
        assert "_manager_call_failures" not in probe.__dict__

        probe._log_warning("первый отказ")

        assert probe.__dict__["_manager_call_failures"] == {"logger.warning": 1}


class TestTrackErrorPicksTheBranchByProtocol:
    """Опасность 4 (найдена прогоном гейта после Т.1): лесенка ``_track_error``
    выбирала вторую ступень по ВОЗВРАЩЁННОМУ ЗНАЧЕНИЮ.

    ``ErrorManager.track_error`` объявлен ``-> None`` и возвращает None на
    ШТАТНОЙ записи, поэтому ``if result is None`` срабатывал всегда и звал
    несуществующий ``record_error``. Пока отсутствующий метод был тихим — цена
    ноль; со счётчиком Т.1 здоровый путь давал ложные «потери» (9 штук за
    прогон гейта фреймворка), и счётчик перестал бы значить «запись потеряна».
    """

    class _TrackOnly:
        """Как настоящий ErrorManager: только track_error, возвращает None."""

        def __init__(self) -> None:
            self.seen: list[Any] = []

        def track_error(self, error: BaseException, context: dict) -> None:
            self.seen.append(error)

    class _RecordOnly:
        """Legacy duck-typed плоскость: только record_error."""

        def __init__(self) -> None:
            self.seen: list[Any] = []

        def record_error(self, error: BaseException, context: dict) -> bool:
            self.seen.append(error)
            return True

    class _Both:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def track_error(self, error: BaseException, context: dict) -> None:
            self.calls.append("track_error")

        def record_error(self, error: BaseException, context: dict) -> bool:
            self.calls.append("record_error")
            return True

    def _probe_with_error_slot(self, slot: Any) -> _Probe:
        probe = _Probe("probe")
        probe.register_manager("error", slot)
        return probe

    def test_track_only_slot_is_not_charged_a_phantom_failure(self) -> None:
        slot = self._TrackOnly()
        probe = self._probe_with_error_slot(slot)

        probe._track_error(ValueError("сбой"))

        assert len(slot.seen) == 1, "инцидент не доехал до track_error"
        assert probe.manager_call_failures == {}, (
            "здоровый путь посчитан отказом — вторая ступень лесенки снова "
            f"выбирается по возвращённому значению: {probe.manager_call_failures!r}"
        )

    def test_record_only_slot_still_works(self) -> None:
        """Legacy-дорога не сломана: у кого нет track_error — зовётся record_error."""
        slot = self._RecordOnly()
        probe = self._probe_with_error_slot(slot)

        probe._track_error(ValueError("сбой"))

        assert len(slot.seen) == 1
        assert probe.manager_call_failures == {}

    def test_both_present_prefers_track_error_exactly_once(self) -> None:
        slot = self._Both()
        probe = self._probe_with_error_slot(slot)

        probe._track_error(ValueError("сбой"))

        assert slot.calls == ["track_error"], f"выбрана не та дорога: {slot.calls}"
        assert probe.manager_call_failures == {}

    def test_slot_with_neither_method_is_loud(self) -> None:
        """Контроль против вакуума: слот, не несущий НИ ОДНОЙ дороги инцидента,
        обязан остаться громким — иначе тесты выше доказывали бы лишь тишину."""
        probe = self._probe_with_error_slot(object())

        probe._track_error(ValueError("сбой"))

        assert probe.manager_call_failures == {"error.record_error": 1}


class TestBothKindsShareOneCounterKey:
    """Смешанный случай: сначала бросил, потом метод пропал (reconfigure
    подменил менеджер). Пара одна — счётчик один, WARNING всё равно один."""

    def test_mixed_failures_accumulate_on_one_key_with_one_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        probe = _Probe("probe", logger=_RaisingWarning())

        with caplog.at_level(logging.WARNING, logger=_MODULE_LOGGER_NAME):
            probe._log_warning("бах")
            probe.register_manager("logger", _NoWarning())
            probe._log_warning("а теперь метода нет")

        assert probe.manager_call_failures == {"logger.warning": 2}
        assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


class TestFalsyManagerIsStillAManager:
    """Находка матрицы инъекций Т.1: ложь на САМОМ менеджере, не на методе.

    Заплата «считать отказом ещё и ``manager is None``» не покраснила ни одного
    теста — и это оказалось не пробелом в тестах, а доказательством, что до
    строки ``if not manager`` ``None`` вообще не доходит: ``ManagerRegistry``
    ставит ``_enabled[name] = manager is not None and enabled``, и слот с
    ``None`` отсекается гейтом ``is_enabled`` выше.

    Значит единственный достижимый случай той строки — менеджер НАСТОЯЩИЙ, но
    ложный по ``__bool__``/``__len__``. Truthiness читала его как «слот пуст»:
    запись исчезала и НЕ считалась, то есть ровно тот дефект, который Т.1
    чинила одной строкой ниже — у метода, — оставался живым у менеджера.
    """

    class _FalsyLogger:
        """Настоящий логгер, у которого ``bool(...)`` — ложь (контейнерный протокол)."""

        def __init__(self) -> None:
            self.seen: list = []

        def __len__(self) -> int:
            return 0

        def warning(self, message, **kwargs) -> str:
            self.seen.append(message)
            return "записано"

    def _make(self, logger):
        class Comp(ObservableMixin):
            def __init__(self, mgr):
                ObservableMixin.__init__(self, managers={"logger": mgr})

        return Comp(logger)

    def test_falsy_manager_still_receives_the_record(self) -> None:
        logger = self._FalsyLogger()
        assert bool(logger) is False, "дубль обязан быть ложным, иначе тест ни о чём"

        comp = self._make(logger)
        comp._log_warning("запись через ложный менеджер")

        assert logger.seen == ["запись через ложный менеджер"], logger.seen

    def test_falsy_manager_is_not_counted_as_a_failure(self) -> None:
        logger = self._FalsyLogger()
        comp = self._make(logger)
        comp._log_warning("запись")

        assert comp.__dict__.get("_manager_call_failures") is None, comp.__dict__.get("_manager_call_failures")

    def test_none_in_the_slot_stays_silent_and_uncounted(self) -> None:
        """Контроль: ``None`` по-прежнему тихий допуск, а не отказ."""
        comp = self._make(None)
        comp._log_warning("запись")

        assert comp.__dict__.get("_manager_call_failures") is None
        assert comp._call_manager("logger", "warning", "x") is None

    def test_falsy_manager_without_the_method_is_loud(self) -> None:
        """Ложный менеджер БЕЗ метода обязан считаться — иначе тишина вернулась."""

        class FalsyNoWarning:
            def __len__(self) -> int:
                return 0

            def log_warning(self, message, **kwargs) -> None:
                pass

        comp = self._make(FalsyNoWarning())
        comp._log_warning("запись")

        assert comp.__dict__.get("_manager_call_failures") == {"logger.warning": 1}, comp.__dict__.get(
            "_manager_call_failures"
        )
