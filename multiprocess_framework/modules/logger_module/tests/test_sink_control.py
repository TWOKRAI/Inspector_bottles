# -*- coding: utf-8 -*-
"""Тесты Ф1 Task 1.4 (серверная часть): LoggerManager.set_sink_enabled.

Якорь ADR-CRM-006 п.3 (logger.sink.enable|disable → register_channel/unregister_channel):
точечная (де)регистрация sink'а по имени без пересборки всего конфига.
"""

from __future__ import annotations

from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager


class TestSetSinkEnabled:
    def test_disable_removes_sink_from_registry(self) -> None:
        mgr = LoggerManager(manager_name="TapTest")
        mgr.initialize()
        assert mgr._channel_registry.get("system_file") is not None

        assert mgr.set_sink_enabled("system_file", False) is True
        assert mgr._channel_registry.get("system_file") is None

    def test_enable_recreates_sink_from_config(self) -> None:
        mgr = LoggerManager(manager_name="TapTest")
        mgr.initialize()
        mgr.set_sink_enabled("system_file", False)
        assert mgr._channel_registry.get("system_file") is None

        assert mgr.set_sink_enabled("system_file", True) is True
        assert mgr._channel_registry.get("system_file") is not None

    def test_enable_unknown_sink_returns_false(self) -> None:
        mgr = LoggerManager(manager_name="TapTest")
        mgr.initialize()
        assert mgr.set_sink_enabled("__nope__", True) is False

    def test_disable_unknown_sink_returns_false(self) -> None:
        mgr = LoggerManager(manager_name="TapTest")
        mgr.initialize()
        assert mgr.set_sink_enabled("__nope__", False) is False
