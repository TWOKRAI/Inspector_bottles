# -*- coding: utf-8 -*-
"""Task Т.1 (наблюдаемость слота "manager present, method missing").

Независимый тестер, ТОЛЬКО по критериям приёмки — реализации не существует.
Красные тесты этого файла — спецификация для разработчика.

Механизм: ``ObservableMixin._call_manager(slot, method_name, *args)`` сегодня
молча возвращает ``None``, если менеджер В СЛОТЕ ЕСТЬ, но у него нет метода
``method_name`` — ``getattr(manager, method_name, None)`` даёт ``None``,
``if method and callable(method)`` не входит, дальше просто ``return None``.
Ни счётчик, ни лог не фиксируют эту потерю — в отличие от исключения ВНУТРИ
менеджера (см. ``_note_manager_call_failure`` / ``manager_call_failures``,
Ф2.3), которое уже посчитано и один раз залогировано.

Критерии (см. ТЗ Task Т.1):
  1. отсутствующий метод — СЧИТАННЫЙ, ВНЕШНЕ ВИДИМЫЙ отказ (счётчик + WARNING
     через stdlib logging, без спама на повторе).
  2. поведенческий тест на РЕАЛЬНОМ компоненте (StateProxy) с логгером,
     у которого нет канонiчных debug/info/warning/error/critical — только
     log_* алиасы.
  3. существующие допуски (a) нет менеджера/None, (b) выключен, (c) менеджер
     бросает исключение — остаются тихими/считанными КАК СЕЙЧАС.
  4. реальная проводка: настоящий LoggerManager + настоящий StateProxy,
     запись реально доезжает до приёмника (MemoryChannel).
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from ..core.base_manager import BaseManager
from ..mixins.observable_mixin import ObservableMixin


# ---------------------------------------------------------------------------
# Локальные дубли (без импорта из test_observable_mixin.py — независимость)
# ---------------------------------------------------------------------------


class _FullLogger:
    """Логгер с полным каноничным протоколом (контроль — НЕ дефектный путь)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def debug(self, msg: str, **kwargs: Any) -> None:
        self.calls.append(("debug", msg))

    def info(self, msg: str, **kwargs: Any) -> None:
        self.calls.append(("info", msg))

    def warning(self, msg: str, **kwargs: Any) -> None:
        self.calls.append(("warning", msg))

    def error(self, msg: str, **kwargs: Any) -> None:
        self.calls.append(("error", msg))

    def critical(self, msg: str, **kwargs: Any) -> None:
        self.calls.append(("critical", msg))


class _PartialLogger:
    """Логгер БЕЗ канонiчного протокола — только info(). warning() отсутствует
    как атрибут вовсе (не заглушка, не raise — метода просто нет)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def info(self, msg: str, **kwargs: Any) -> None:
        self.calls.append(("info", msg))


class _LogPrefixedLogger:
    """Логгер реальных объектов проекта (StateProxy получает такие как
    logger=): экспонирует ТОЛЬКО log_debug/log_info/log_warning/... — не
    debug/info/warning/... ObservableMixin зовёт канонiчные имена, поэтому
    КАЖДАЯ запись такого компонента сегодня тихо исчезает."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def log_debug(self, msg: str, **kwargs: Any) -> None:
        self.calls.append(("log_debug", msg))

    def log_info(self, msg: str, **kwargs: Any) -> None:
        self.calls.append(("log_info", msg))

    def log_warning(self, msg: str, **kwargs: Any) -> None:
        self.calls.append(("log_warning", msg))

    def log_error(self, msg: str, **kwargs: Any) -> None:
        self.calls.append(("log_error", msg))

    def log_critical(self, msg: str, **kwargs: Any) -> None:
        self.calls.append(("log_critical", msg))


class _RaisingLogger:
    """Менеджер В СЛОТЕ ЕСТЬ, метод ЕСТЬ, но бросает исключение (допуск (c),
    Ф2.3 — уже посчитан и залогирован ДО этой задачи; пиновка регрессии)."""

    def warning(self, msg: str, **kwargs: Any) -> None:
        raise RuntimeError("сломанный sink")


_MODULE_LOGGER_NAME = "multiprocess_framework.modules.base_manager.mixins.observable_mixin"


class _Probe(BaseManager, ObservableMixin):
    """Минимальный наследник BaseManager+ObservableMixin для стенда."""

    __test__ = False

    def __init__(self, name: str, logger: Any = None) -> None:
        BaseManager.__init__(self, name)
        managers: dict[str, Any] = {}
        if logger is not None:
            managers["logger"] = logger
        ObservableMixin.__init__(self, managers=managers, config={k: True for k in managers})

    def initialize(self) -> bool:
        self.is_initialized = True
        return True

    def shutdown(self) -> bool:
        self.is_initialized = False
        return True


# ---------------------------------------------------------------------------
# Критерий 1 — отсутствующий метод: счётчик + WARNING, без спама
# ---------------------------------------------------------------------------


class TestMissingMethodIsCountedAndVisible:
    def test_missing_method_grows_a_counter_readable_from_outside(self) -> None:
        """Счётчик обязан расти при КАЖДОМ вызове отсутствующего метода —
        сегодня manager_call_failures вообще не трогается на этом пути
        (никакого except не срабатывает, просто return None)."""
        probe = _Probe("probe", logger=_PartialLogger())

        probe._log_warning("первый")
        probe._log_warning("второй")

        failures = probe.manager_call_failures
        assert failures.get("logger.warning") == 2, f"счётчик отсутствующего метода не растёт: {failures!r}"

    def test_missing_method_emits_one_stdlib_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Человеко-видимый сигнал — WARNING через stdlib logging (как для
        исключения внутри менеджера, Ф2.3), а не тишина."""
        probe = _Probe("probe", logger=_PartialLogger())

        with caplog.at_level(logging.WARNING, logger=_MODULE_LOGGER_NAME):
            probe._log_warning("нет такого метода")

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1, f"ожидался ровно один WARNING, получено: {warnings!r}"
        assert "logger.warning" in warnings[0].getMessage()

    def test_repeated_identical_calls_warn_once_but_counter_keeps_growing(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Симметрия с допуском (c): первый раз — WARNING, дальше — только
        счётчик (hot-path, спам недопустим)."""
        probe = _Probe("probe", logger=_PartialLogger())

        with caplog.at_level(logging.WARNING, logger=_MODULE_LOGGER_NAME):
            probe._log_warning("раз")
            probe._log_warning("два")
            probe._log_warning("три")

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1, f"WARNING продублировался на повторе: {warnings!r}"
        assert probe.manager_call_failures.get("logger.warning") == 3

    def test_different_missing_methods_are_counted_separately(self) -> None:
        """Пара 'logger.info' и 'logger.warning' — разные ключи (симметрия с
        уже существующей раскладкой в TestCallManagerFailureAccounting)."""
        probe = _Probe("probe", logger=_PartialLogger())

        probe._log_warning("w")  # info есть, warning — нет
        probe._log_error("e")  # error тоже отсутствует

        failures = probe.manager_call_failures
        assert failures.get("logger.warning") == 1
        assert failures.get("logger.error") == 1


# ---------------------------------------------------------------------------
# Критерий 2 — поведенческий тест на РЕАЛЬНОМ компоненте (StateProxy)
# ---------------------------------------------------------------------------


class TestRealComponentWithLogPrefixedLogger:
    """StateProxy, которому подсунут логгер реального проекта (только
    log_warning, не warning) — производит ВИДИМЫЙ сигнал, а не пустоту."""

    def _make_proxy(self, logger: Any) -> Any:
        from multiprocess_framework.modules.state_store_module.proxy.state_proxy import StateProxy

        return StateProxy("probe_process", router=None, logger=logger)

    def test_log_prefixed_logger_call_is_counted(self) -> None:
        logger = _LogPrefixedLogger()
        proxy = self._make_proxy(logger)

        proxy._log_warning("предупреждение от StateProxy")

        assert proxy.manager_call_failures.get("logger.warning") == 1, (
            f"StateProxy с log_warning-only логгером не посчитал отказ: {proxy.manager_call_failures!r}"
        )
        # Контроль: сообщение реально НЕ дошло каноничным путём (логгер его
        # не увидел под именем warning()) — иначе тест ничего не доказывает.
        assert logger.calls == []

    def test_log_prefixed_logger_call_emits_stdlib_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = _LogPrefixedLogger()
        proxy = self._make_proxy(logger)

        with caplog.at_level(logging.WARNING, logger=_MODULE_LOGGER_NAME):
            proxy._log_warning("предупреждение от StateProxy")

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1, f"StateProxy: ожидался один WARNING, получено {warnings!r}"


# ---------------------------------------------------------------------------
# Критерий 3 — существующие допуски НЕ должны стать шумом
# ---------------------------------------------------------------------------


class TestExistingTolerancesStayQuiet:
    def test_no_manager_registered_is_silent(self) -> None:
        """(a) слот не зарегистрирован вовсе."""
        probe = _Probe("probe")  # без logger= вообще
        probe._log_warning("в пустоту")
        assert probe.manager_call_failures == {}

    def test_manager_is_none_is_silent(self) -> None:
        """(a2) менеджер зарегистрирован, но значение — None."""
        probe = _Probe("probe")
        probe.register_manager("logger", None)
        probe._log_warning("в пустоту")
        assert probe.manager_call_failures == {}

    def test_disabled_manager_is_silent_even_with_missing_method(self) -> None:
        """(b) слот выключен — та же тишина, ДАЖЕ если метод у менеджера
        отсутствует (выключенность проверяется раньше поиска метода)."""
        probe = _Probe("probe", logger=_PartialLogger())
        probe.disable("logger")

        probe._log_warning("выключено")

        assert probe.manager_call_failures == {}

    def test_manager_raises_is_still_counted_as_before(self) -> None:
        """(c) регрессионная пиновка Ф2.3 — не переиспользуем чужой тест,
        доказываем литералом заново в этом файле."""
        probe = _Probe("probe", logger=_RaisingLogger())

        probe._log_warning("бах")

        assert probe.manager_call_failures == {"logger.warning": 1}

    def test_manager_raises_emits_exactly_one_warning_not_two(self, caplog: pytest.LogCaptureFixture) -> None:
        """Пограничный случай: исключение — это НЕ то же самое, что
        отсутствующий метод, и они не должны задваивать WARNING на одном
        вызове."""
        probe = _Probe("probe", logger=_RaisingLogger())

        with caplog.at_level(logging.WARNING, logger=_MODULE_LOGGER_NAME):
            probe._log_warning("бах")

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1


# ---------------------------------------------------------------------------
# Критерий 4 — реальная проводка: LoggerManager + StateProxy, запись
# доезжает до приёмника (не только "счётчик сказал сдано")
# ---------------------------------------------------------------------------


class _RequestNoneRouter:
    """Минимальный дубль IRouter: request() всегда возвращает None (как при
    таймауте/отказе транспорта) — провоцирует StateProxy.subscribe() уйти по
    WARNING-ветке 'подписка не подтверждена сервером' РЕАЛЬНЫМ публичным
    путём, а не прямым вызовом _log_warning."""

    def request(self, msg: dict, timeout: float = 5.0):  # noqa: ARG002
        return None

    def send_async(self, msg: dict, priority: str = "normal") -> None:  # noqa: ARG002
        return None


class TestRealWiringLoggerManagerAndStateProxy:
    """Настоящий LoggerManager (кольцо в памяти) + настоящий StateProxy —
    запись реально доезжает до приёмника, а не просто "менеджер существует"."""

    @pytest.fixture()
    def logger_manager(self, tmp_path):
        from multiprocess_framework.modules.logger_module.configs import (
            LoggerChannelSchema,
            LoggerManagerConfig,
            LoggerScopeSchema,
        )
        from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

        scopes = ("SYSTEM", "BUSINESS", "PERFORMANCE", "DEBUG")
        manager = LoggerManager(
            config=LoggerManagerConfig(
                app_name="t1_tester",
                log_directory=str(tmp_path),
                enable_batching=False,
                modules={},
                channels={"ring": LoggerChannelSchema(type="memory", enabled=True, capacity=200)},
                default_level="DEBUG",
                scopes={name: LoggerScopeSchema(channels=["ring"]) for name in scopes},
            )
        )
        yield manager
        manager.shutdown()

    def test_state_proxy_warning_reaches_the_logger_manager_ring(self, logger_manager) -> None:
        """StateProxy.subscribe() по РЕАЛЬНОМУ публичному пути (router с
        отказавшим request()) обязан породить WARNING-запись, которую можно
        прочитать через сам LoggerManager (read_sink_tail), а не только
        проверить, что метод был вызван на подставном объекте."""
        from multiprocess_framework.modules.state_store_module.proxy.state_proxy import StateProxy

        proxy = StateProxy(
            "probe_process",
            router=_RequestNoneRouter(),
            logger=logger_manager,
        )

        proxy.subscribe("cameras.*.config.*", callback=lambda _deltas: None, sync=True)

        records = logger_manager.read_sink_tail("ring")["records"]
        warning_records = [r for r in records if r.get("level") == "WARNING"]
        assert warning_records, f"ни одной WARNING-записи не доехало до кольца LoggerManager: {records!r}"
        assert any("cameras.*.config.*" in r.get("message", "") for r in warning_records), (
            f"WARNING-запись доехала, но без ожидаемого текста подписки: {warning_records!r}"
        )
