# -*- coding: utf-8 -*-
"""Независимые тесты контракта StdLoggerFacade — поддержка kwargs stdlib (задача 6.1).

Пишутся СТРОГО по критериям приёмки задачи 6.1 плана
``plans/observability-unified-routing.md``, без чтения реализации
``adapters/std_facade.py`` и текущего diff. Источник контракта — публичный
README модуля (раздел "Прикладной код в stdlib-стиле") и существующие тесты
``test_std_facade.py`` / ``test_lazy_message.py`` как образец харнесса.

Файл НЕ переиспользует фейки/фикстуры соседних тестовых файлов напрямую —
это независимая проверка, а не расширение авторских тестов.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.logger_module.adapters import std_facade
from multiprocess_framework.modules.logger_module.adapters.std_facade import StdLoggerFacade
from multiprocess_framework.modules.logger_module.core.logger_core import bump_observability_epoch
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


def _manager(tmp_path: Path, **overrides: Any) -> LoggerManager:
    """Настоящий LoggerManager: DEBUG-скоуп закрыт, SYSTEM/BUSINESS открыты.

    Закрытый DEBUG нужен для критерия 10 (отложенность) — образец конфигурации
    взят из test_lazy_message.py::_manager.
    """
    config: Dict[str, Any] = {
        "app_name": "std_facade_kwargs",
        "log_directory": str(tmp_path),
        "enable_batching": False,
        "modules": {},
        "channels": {
            "a": {"type": "file", "enabled": True, "file_path": str(tmp_path / "a.log")},
        },
        "scopes": {
            "BUSINESS": {"enabled": True, "min_level": "INFO", "channels": ["a"]},
            "SYSTEM": {"enabled": True, "min_level": "WARNING", "channels": ["a"]},
            "DEBUG": {"enabled": False, "min_level": "DEBUG", "channels": ["a"]},
        },
    }
    config.update(overrides)
    mgr = LoggerManager(manager_name="StdFacadeKwargsProbe", config=config)
    mgr.initialize()
    return mgr


@pytest.fixture
def real_logger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Реальный менеджер, подключённый к фасаду напрямую (без ObservableMixin)."""
    mgr = _manager(tmp_path)
    monkeypatch.setattr(std_facade, "get_logger", lambda: mgr)
    bump_observability_epoch()
    yield mgr
    mgr.shutdown()


@pytest.fixture
def no_lm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Режим «LoggerManager не поднят» — фолбэк на stdlib logging."""
    monkeypatch.setattr(std_facade, "get_logger", lambda: None)
    bump_observability_epoch()


class _FakeManager:
    """Минимальный дубль LoggerManager, повторяющий сигнатуру ``log()``.

    Нужен только там, где важно увидеть СЫРЫЕ kwargs, дошедшие до менеджера
    (критерий 6) — файловый канал такую проверку не даёт напрямую.
    """

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def log(self, scope: Any, level: Any, message: Any, module: str = "main", *args: Any, **extra: Any) -> None:
        resolved = message() if callable(message) else message
        self.calls.append(
            {"scope": scope, "level": level, "message": resolved, "module": module, "args": args, "extra": extra}
        )


@pytest.fixture
def fake_logger(monkeypatch: pytest.MonkeyPatch) -> _FakeManager:
    fake = _FakeManager()
    monkeypatch.setattr(std_facade, "get_logger", lambda: fake)
    bump_observability_epoch()
    return fake


class _CountingException(ValueError):
    """Исключение, чей ``__str__`` считает вызовы — критерий 10.

    Счётчик на объекте, а не шпион на имени функции форматирования: свойство
    "дорогое не вычисляется при закрытом гейте" наблюдается по факту вызова
    ``__str__``, а не по тому, как именно реализация рендерит traceback.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.str_calls = 0

    def __str__(self) -> str:
        self.str_calls += 1
        return super().__str__()


def _read(tmp_path: Path) -> str:
    return (tmp_path / "a.log").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Критерий 1 — все методы принимают exc_info=/extra= и не падают
# ---------------------------------------------------------------------------


class TestKwargsAccepted:
    @pytest.mark.parametrize("level", ["debug", "info", "warning", "error", "critical", "exception"])
    def test_level_method_accepts_exc_info_and_extra(self, real_logger: LoggerManager, level: str) -> None:
        facade = StdLoggerFacade("probe")
        method = getattr(facade, level)

        method("сообщение", exc_info=None, extra={"trace_id": "abc"})  # не должно бросить

    def test_log_accepts_exc_info_and_extra(self, real_logger: LoggerManager) -> None:
        facade = StdLoggerFacade("probe")

        facade.log("INFO", "сообщение", exc_info=None, extra={"trace_id": "abc"})  # не должно бросить


# ---------------------------------------------------------------------------
# Критерий 2/3 — exc_info=True внутри/вне except
# ---------------------------------------------------------------------------


class TestExcInfoTrue:
    def test_inside_except_includes_exception_type_message_and_traceback(
        self, real_logger: LoggerManager, tmp_path: Path
    ) -> None:
        facade = StdLoggerFacade("probe")

        try:
            raise ValueError("бум")
        except ValueError:
            facade.error("операция упала", exc_info=True)
        real_logger.flush()

        text = _read(tmp_path)
        assert "ValueError" in text
        assert "бум" in text
        assert "Traceback" in text

    def test_outside_except_has_no_traceback_noise(self, real_logger: LoggerManager, tmp_path: Path) -> None:
        facade = StdLoggerFacade("probe")

        facade.error("просто ошибка", exc_info=True)  # активного исключения нет
        real_logger.flush()

        text = _read(tmp_path)
        assert "просто ошибка" in text
        assert "NoneType" not in text
        assert "Traceback" not in text


# ---------------------------------------------------------------------------
# Критерий 4 — варианты exc_info: объект исключения, кортеж, False/None
# ---------------------------------------------------------------------------


class TestExcInfoVariants:
    def test_exception_instance_gives_same_effect_as_true(self, real_logger: LoggerManager, tmp_path: Path) -> None:
        facade = StdLoggerFacade("probe")

        try:
            raise ValueError("бум-объект")
        except ValueError as caught:
            exc = caught

        facade.error("через объект", exc_info=exc)
        real_logger.flush()

        text = _read(tmp_path)
        assert "ValueError" in text
        assert "бум-объект" in text
        assert "Traceback" in text

    def test_three_item_tuple_gives_same_effect_as_true(self, real_logger: LoggerManager, tmp_path: Path) -> None:
        facade = StdLoggerFacade("probe")

        try:
            raise ValueError("бум-кортеж")
        except ValueError:
            info = sys.exc_info()

        facade.error("через кортеж", exc_info=info)
        real_logger.flush()

        text = _read(tmp_path)
        assert "ValueError" in text
        assert "бум-кортеж" in text
        assert "Traceback" in text

    def test_false_gives_no_effect(self, real_logger: LoggerManager, tmp_path: Path) -> None:
        facade = StdLoggerFacade("probe")

        try:
            raise ValueError("должен быть проигнорирован (False)")
        except ValueError:
            facade.error("без traceback false", exc_info=False)
        real_logger.flush()

        text = _read(tmp_path)
        assert "без traceback false" in text
        assert "Traceback" not in text
        assert "проигнорирован" not in text

    def test_none_gives_no_effect(self, real_logger: LoggerManager, tmp_path: Path) -> None:
        facade = StdLoggerFacade("probe")

        try:
            raise ValueError("должен быть проигнорирован (None)")
        except ValueError:
            facade.error("без traceback none", exc_info=None)
        real_logger.flush()

        text = _read(tmp_path)
        assert "без traceback none" in text
        assert "Traceback" not in text
        assert "проигнорирован" not in text


# ---------------------------------------------------------------------------
# Критерий 5 — %-форматирование вместе с exc_info
# ---------------------------------------------------------------------------


class TestPercentFormatWithExcInfo:
    def test_percent_args_and_traceback_both_present(self, real_logger: LoggerManager, tmp_path: Path) -> None:
        facade = StdLoggerFacade("probe")

        try:
            raise RuntimeError("движок упал")
        except RuntimeError:
            facade.error("код %s", 42, exc_info=True)
        real_logger.flush()

        text = _read(tmp_path)
        assert "код 42" in text
        assert "%s" not in text
        assert "Traceback" in text
        assert "RuntimeError" in text
        assert "движок упал" in text


# ---------------------------------------------------------------------------
# Критерий 6 — extra доезжает до менеджера как поле записи (kwargs LoggerCore.log)
# ---------------------------------------------------------------------------


class TestExtraReachesManager:
    def test_extra_field_reaches_manager_as_kwarg(self, fake_logger: _FakeManager) -> None:
        StdLoggerFacade("probe").info("сообщение", extra={"trace_id": "abc"})

        assert len(fake_logger.calls) == 1
        assert fake_logger.calls[0]["extra"].get("trace_id") == "abc"


# ---------------------------------------------------------------------------
# Критерий 7 — stacklevel не поддерживается: TypeError
# ---------------------------------------------------------------------------


class TestStacklevelUnsupported:
    def test_stacklevel_raises_type_error(self, real_logger: LoggerManager) -> None:
        facade = StdLoggerFacade("probe")

        with pytest.raises(TypeError):
            facade.warning("x", stacklevel=2)


# ---------------------------------------------------------------------------
# Критерий 8 — режим «менеджера нет» (фолбэк stdlib)
# ---------------------------------------------------------------------------


class TestFallbackWithoutManager:
    def test_exc_info_true_inside_except_reaches_caplog(self, no_lm: None, caplog: pytest.LogCaptureFixture) -> None:
        facade = StdLoggerFacade("probe")

        with caplog.at_level(logging.ERROR, logger="mpf.probe"):
            try:
                raise ValueError("фолбэк-ошибка")
            except ValueError:
                facade.error("упало в фолбэке", exc_info=True)

        assert "Traceback" in caplog.text
        assert "ValueError" in caplog.text
        assert "фолбэк-ошибка" in caplog.text

    def test_extra_does_not_crash_the_call(self, no_lm: None, caplog: pytest.LogCaptureFixture) -> None:
        facade = StdLoggerFacade("probe")

        with caplog.at_level(logging.INFO, logger="mpf.probe"):
            facade.info("сообщение с extra", extra={"trace_id": "abc"})  # не должно бросить

        assert "сообщение с extra" in caplog.text


# ---------------------------------------------------------------------------
# Критерий 9 — extra с именем, совпадающим с позиционным параметром log()
# ---------------------------------------------------------------------------


class TestExtraReservedNameCollision:
    @pytest.mark.parametrize("reserved_key", ["scope", "level", "message", "module"])
    def test_reserved_key_in_extra_does_not_raise_inside_except(
        self, real_logger: LoggerManager, reserved_key: str
    ) -> None:
        facade = StdLoggerFacade("probe")

        try:
            raise ValueError("коллизия имени поля")
        except ValueError:
            # Не должно поднять TypeError ("got multiple values for argument ...")
            facade.error("сообщение", exc_info=True, extra={reserved_key: "коллизия"})


# ---------------------------------------------------------------------------
# Критерий 10 — отложенность: traceback не рендерится при закрытом гейте
# ---------------------------------------------------------------------------


class TestLazyTracebackRendering:
    def test_not_rendered_when_gate_closed(self, real_logger: LoggerManager) -> None:
        facade = StdLoggerFacade("probe")
        exc = _CountingException("закрытый гейт")

        try:
            raise exc
        except _CountingException:
            # debug() -> LogScope.DEBUG, выключен в конфигурации фикстуры.
            facade.debug("отладочное сообщение", exc_info=True)

        assert exc.str_calls == 0, "traceback отрендерен, хотя запись отклонена закрытым гейтом"

    def test_rendered_when_gate_open(self, real_logger: LoggerManager) -> None:
        facade = StdLoggerFacade("probe")
        exc = _CountingException("открытый гейт")

        try:
            raise exc
        except _CountingException:
            # error() -> LogScope.SYSTEM, открыт в конфигурации фикстуры.
            facade.error("сообщение", exc_info=True)

        assert exc.str_calls > 0, "traceback НЕ отрендерен при открытом гейте — пара критерия 10 нарушена"
