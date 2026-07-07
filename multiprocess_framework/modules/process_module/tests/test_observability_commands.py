# -*- coding: utf-8 -*-
"""Тесты Ф1 Task 1.4: IPC config.reload / logger.sink.enable|disable.

Реализация ADR-CRM-006 п.3 поверх готовых reconfigure/sink-реестра. Проверяем:
  - команды регистрируются в CommandManager с описанием (для контактной книжки 1.9);
  - config.reload с inline-override меняет уровень логгера через reconfigure (тот же
    путь, что hot-reload watcher — apply_observability_reconfigure);
  - logger.sink.enable|disable делегируют в LoggerManager.set_sink_enabled.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands


class _FakeCommandManager:
    def __init__(self) -> None:
        self.handlers: dict = {}
        self.metadata: dict = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler
        self.metadata[name] = metadata or {}

    def dispatch(self, command: str, data: dict | None = None) -> dict:
        return self.handlers[command](data or {})


class _FakeLogger:
    """Логгер: фиксирует reconfigure(dict) и set_sink_enabled(name, bool)."""

    def __init__(self) -> None:
        self.reconfigured: list = []
        self.sink_calls: list = []
        self.sinks = {"errors_file"}  # «зарегистрированные» sink'и

    def reconfigure(self, config: dict) -> bool:
        self.reconfigured.append(config)
        return True

    def set_sink_enabled(self, name: str, enabled: bool) -> bool:
        self.sink_calls.append((name, enabled))
        if enabled:
            self.sinks.add(name)
            return True
        if name in self.sinks:
            self.sinks.discard(name)
            return True
        return False


class _FakeTapLogger:
    """Логгер с tap-API (add_log_tap / remove_log_tap)."""

    manager_name = "LoggerManager"

    def __init__(self) -> None:
        self.taps: dict = {}

    def add_log_tap(self, channel, *, min_level="ERROR", name=None) -> str:
        tap = name or getattr(channel, "name", "tap")
        self.taps[tap] = (channel, min_level)
        return tap

    def remove_log_tap(self, name) -> bool:
        return self.taps.pop(name, None) is not None


class _FakeRouter:
    def send_async(self, message, priority="normal") -> None: ...


class _FakeServices:
    def __init__(self, *, logger=None, config=None, router=None) -> None:
        self.command_manager = _FakeCommandManager()
        self.logger_manager = logger
        self.error_manager = None
        self.stats_manager = None
        self.router_manager = router
        self.name = "preprocessor"
        self._config = config or {}

    def get_config(self, key, default=None):
        return self._config.get(key, default)

    def _log_info(self, *a, **k) -> None: ...
    def _log_debug(self, *a, **k) -> None: ...


def _make(**kw):
    svc = _FakeServices(**kw)
    bc = BuiltinCommands(svc)
    bc._register_observability_commands()
    return svc, svc.command_manager


class TestRegistration:
    def test_registers_commands_with_descriptions(self) -> None:
        _svc, cm = _make(logger=_FakeLogger())
        for key in (
            "config.reload",
            "logger.sink.enable",
            "logger.sink.disable",
            "log.tail.subscribe",
            "log.tail.unsubscribe",
        ):
            assert key in cm.handlers
            assert cm.metadata[key].get("description"), f"{key}: нет description (нужно для 1.9)"

    def test_skips_without_command_manager(self) -> None:
        svc = _FakeServices(logger=_FakeLogger())
        svc.command_manager = None
        BuiltinCommands(svc)._register_observability_commands()  # не должно падать


class TestConfigReload:
    def test_inline_override_changes_log_level(self) -> None:
        logger = _FakeLogger()
        _svc, cm = _make(logger=logger)
        res = cm.dispatch("config.reload", {"observability": {"log_level": "DEBUG"}})
        assert res["success"] is True
        assert res["applied"]["log_level"] == "DEBUG"
        # reconfigure получил развёрнутый logger-конфиг с новым уровнем
        assert logger.reconfigured, "reconfigure не вызван"
        assert logger.reconfigured[-1].get("default_level") == "DEBUG"

    def test_no_section_no_path_returns_error(self) -> None:
        _svc, cm = _make(logger=_FakeLogger(), config={})
        res = cm.dispatch("config.reload", {})
        assert res["success"] is False
        assert "observability" in res["reason"]


class TestLoggerSink:
    def test_disable_then_enable_sink(self) -> None:
        logger = _FakeLogger()
        _svc, cm = _make(logger=logger)

        off = cm.dispatch("logger.sink.disable", {"sink": "errors_file"})
        assert off["success"] is True and off["enabled"] is False
        assert "errors_file" not in logger.sinks

        on = cm.dispatch("logger.sink.enable", {"sink": "errors_file"})
        assert on["success"] is True and on["enabled"] is True
        assert "errors_file" in logger.sinks

    def test_missing_sink_name_is_error(self) -> None:
        _svc, cm = _make(logger=_FakeLogger())
        res = cm.dispatch("logger.sink.enable", {})
        assert res["success"] is False


class TestLogTail:
    def test_subscribe_installs_tap(self) -> None:
        logger = _FakeTapLogger()
        svc, cm = _make(logger=logger, router=_FakeRouter())
        res = cm.dispatch("log.tail.subscribe", {"subscriber": "backend_ctl", "level": "ERROR"})
        assert res["success"] is True
        assert res["level"] == "ERROR"
        assert res["tap"] == "log_tail::backend_ctl"
        assert "log_tail::backend_ctl" in logger.taps

    def test_subscribe_requires_subscriber(self) -> None:
        _svc, cm = _make(logger=_FakeTapLogger(), router=_FakeRouter())
        assert cm.dispatch("log.tail.subscribe", {})["success"] is False

    def test_subscribe_requires_router(self) -> None:
        _svc, cm = _make(logger=_FakeTapLogger(), router=None)
        res = cm.dispatch("log.tail.subscribe", {"subscriber": "backend_ctl"})
        assert res["success"] is False
        assert "router" in res["reason"]

    def test_unsubscribe_removes_tap(self) -> None:
        logger = _FakeTapLogger()
        _svc, cm = _make(logger=logger, router=_FakeRouter())
        cm.dispatch("log.tail.subscribe", {"subscriber": "backend_ctl"})
        res = cm.dispatch("log.tail.unsubscribe", {"subscriber": "backend_ctl"})
        assert res["success"] is True
        assert logger.taps == {}
