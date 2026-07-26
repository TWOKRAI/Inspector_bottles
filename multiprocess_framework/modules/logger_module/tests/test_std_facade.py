# -*- coding: utf-8 -*-
"""Тесты StdLoggerFacade — моста «stdlib-стиль» → LoggerManager.

Ключевой инвариант: сообщение не исчезает ни в одном из режимов.
Есть LoggerManager — пишем в него; нет — в stdlib, но не в никуда.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from multiprocess_framework.modules.logger_module.adapters import std_facade
from multiprocess_framework.modules.logger_module.adapters.std_facade import (
    StdLoggerFacade,
    get_std_logger,
)


class _FakeLoggerManager:
    """Минимальный дубль LoggerManager: собирает (level, message, module)."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str, str]] = []

    def _capture(self, level: str, message: str, module: str) -> None:
        self.records.append((level, message, module))

    def debug(self, message: str, module: str = "main", **_extra: Any) -> None:
        self._capture("debug", message, module)

    def info(self, message: str, module: str = "main", **_extra: Any) -> None:
        self._capture("info", message, module)

    def warning(self, message: str, module: str = "main", **_extra: Any) -> None:
        self._capture("warning", message, module)

    def error(self, message: str, module: str = "main", **_extra: Any) -> None:
        self._capture("error", message, module)

    def critical(self, message: str, module: str = "main", **_extra: Any) -> None:
        self._capture("critical", message, module)


@pytest.fixture
def fake_lm(monkeypatch: pytest.MonkeyPatch) -> _FakeLoggerManager:
    """Подменить get_logger() внутри фасада на фейковый менеджер."""
    lm = _FakeLoggerManager()
    monkeypatch.setattr(std_facade, "get_logger", lambda: lm)
    return lm


@pytest.fixture
def no_lm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Режим «LoggerManager не поднят»."""
    monkeypatch.setattr(std_facade, "get_logger", lambda: None)


class TestRoutingToLoggerManager:
    """Есть LoggerManager — запись уходит в него с нужным module."""

    @pytest.mark.parametrize("level", ["debug", "info", "warning", "error", "critical"])
    def test_each_level_reaches_manager(self, fake_lm: _FakeLoggerManager, level: str) -> None:
        facade = StdLoggerFacade("gui")

        assert getattr(facade, level)("сообщение") is True

        assert fake_lm.records == [(level, "сообщение", "gui")]

    def test_percent_args_formatted(self, fake_lm: _FakeLoggerManager) -> None:
        """%-аргументы склеиваются, как в stdlib."""
        StdLoggerFacade("gui").warning("процесс '%s' не найден (код %d)", "pult", 42)

        assert fake_lm.records[0][1] == "процесс 'pult' не найден (код 42)"

    def test_module_is_passed_through(self, fake_lm: _FakeLoggerManager) -> None:
        StdLoggerFacade("trace").info("x")

        assert fake_lm.records[0][2] == "trace"

    def test_broken_format_does_not_swallow_message(self, fake_lm: _FakeLoggerManager) -> None:
        """Кривой формат — не повод потерять запись целиком."""
        StdLoggerFacade("gui").warning("нет плейсхолдеров", "лишний")

        assert len(fake_lm.records) == 1
        assert "нет плейсхолдеров" in fake_lm.records[0][1]
        assert "лишний" in fake_lm.records[0][1]


class TestFallbackWithoutManager:
    """Нет LoggerManager — stdlib, а не тишина (иначе это второй проглот)."""

    def test_falls_back_to_stdlib(self, no_lm: None, caplog: pytest.LogCaptureFixture) -> None:
        facade = StdLoggerFacade("gui")

        with caplog.at_level(logging.WARNING, logger="mpf.gui"):
            emitted_to_manager = facade.warning("расхождение конфига и рантайма")

        assert emitted_to_manager is False, "без менеджера возвращаем False — запись ушла в фолбэк"
        assert "расхождение конфига и рантайма" in caplog.text

    def test_fallback_logger_name_is_derived_from_module(self, no_lm: None) -> None:
        assert StdLoggerFacade("camera")._fallback.name == "mpf.camera"

    def test_explicit_fallback_name(self, no_lm: None) -> None:
        assert StdLoggerFacade("gui", fallback_name="custom")._fallback.name == "custom"


class TestLazyResolve:
    """Фасад создаётся до init_logging — связывание обязано быть ленивым."""

    def test_manager_appearing_later_is_picked_up(self, monkeypatch: pytest.MonkeyPatch) -> None:
        holder: dict[str, Any] = {"lm": None}
        monkeypatch.setattr(std_facade, "get_logger", lambda: holder["lm"])

        facade = StdLoggerFacade("gui")  # создан, когда менеджера ещё нет
        assert facade.warning("до init") is False

        holder["lm"] = _FakeLoggerManager()
        assert facade.warning("после init") is True
        assert holder["lm"].records[0][1] == "после init"


class TestExceptionAndLog:
    def test_exception_appends_traceback(self, fake_lm: _FakeLoggerManager) -> None:
        facade = StdLoggerFacade("gui")
        try:
            raise ValueError("бум")
        except ValueError:
            facade.exception("операция упала")

        level, message, _ = fake_lm.records[0]
        assert level == "error"
        assert "операция упала" in message
        assert "ValueError: бум" in message, "traceback обязан попасть в текст: exc_info у LM нет"

    def test_exception_outside_handler_has_no_traceback_noise(self, fake_lm: _FakeLoggerManager) -> None:
        """Вне except traceback пустой — не приклеивать 'NoneType: None'."""
        StdLoggerFacade("gui").exception("просто ошибка")

        assert fake_lm.records[0][1] == "просто ошибка"

    def test_log_with_string_level(self, fake_lm: _FakeLoggerManager) -> None:
        StdLoggerFacade("gui").log("WARNING", "смешанный регистр")

        assert fake_lm.records[0][0] == "warning"

    def test_unknown_level_degrades_to_info(self, fake_lm: _FakeLoggerManager) -> None:
        """Опечатка в уровне не должна ронять или глотать запись."""
        StdLoggerFacade("gui").log("warninng", "опечатка")

        assert fake_lm.records[0] == ("info", "опечатка", "gui")


class TestFactory:
    def test_same_module_returns_same_instance(self) -> None:
        assert get_std_logger("gui") is get_std_logger("gui")

    def test_different_modules_are_distinct(self) -> None:
        assert get_std_logger("gui") is not get_std_logger("trace")
        assert get_std_logger("trace").module == "trace"
