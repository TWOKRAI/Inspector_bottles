# -*- coding: utf-8 -*-
"""Тесты гейта ``log_success`` CommandManager (шум рутинного успеха, живая находка 2026-07-21).

Контракт: по умолчанию успех штатной команды НЕ логируется — и НЕ форматируется
(гейт у источника, не фильтр на выходе, см. ``observability.commands.log_success``
в ``process_module/configs/observability_config.py``). Явный переключатель включает
запись обратно. Ошибки/неуспех команд логируются ВСЕГДА, независимо от гейта —
режем только шум успеха, не диагностику.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from multiprocess_framework.modules.command_module.core.command_manager import CommandManager


def _manager(**config: bool) -> CommandManager:
    mgr = CommandManager("probe", config=dict(config))
    mgr.initialize()
    mgr.register_command("ping", lambda data: {"ok": True})
    mgr.register_command("boom", lambda data: (_ for _ in ()).throw(RuntimeError("boom")))
    return mgr


class TestLogSuccessGatePair:
    """Пара ON/OFF: по умолчанию тишина, явное включение — лог есть."""

    def test_default_off_success_not_logged(self) -> None:
        mgr = _manager()  # без log_success в config -> False (см. __init__)
        mgr._log_info = MagicMock()

        mgr.handle_command({"command": "ping", "data": {}})

        # _log_info вообще не вызван: f-string с именем команды и длительностью
        # существует только ВНУТРИ аргумента этого вызова, под тем же if, что
        # и сам вызов, — значит "0 вызовов" означает и "строка не построена".
        mgr._log_info.assert_not_called()

    def test_explicit_on_success_is_logged(self) -> None:
        mgr = _manager(log_success=True)
        mgr._log_info = MagicMock()

        mgr.handle_command({"command": "ping", "data": {}})

        mgr._log_info.assert_called_once()
        (msg,), kwargs = mgr._log_info.call_args
        assert "ping" in msg
        assert "executed successfully" in msg
        assert kwargs.get("module") == "command_manager"

    def test_setter_flips_gate_at_runtime(self) -> None:
        """set_log_success_enabled — та же пара, но через runtime-переключатель."""
        mgr = _manager()
        mgr._log_info = MagicMock()

        mgr.handle_command({"command": "ping", "data": {}})
        mgr._log_info.assert_not_called()

        mgr.set_log_success_enabled(True)
        mgr.handle_command({"command": "ping", "data": {}})
        mgr._log_info.assert_called_once()

        mgr.set_log_success_enabled(False)
        mgr._log_info.reset_mock()
        mgr.handle_command({"command": "ping", "data": {}})
        mgr._log_info.assert_not_called()


class TestErrorsAlwaysLoggedRegardlessOfGate:
    """Режем только шум успеха — ошибки/неуспех логируются всегда."""

    def test_errors_logged_when_gate_off(self) -> None:
        mgr = _manager(log_success=False)
        mgr._log_warning = MagicMock()

        mgr.handle_command({"command": "boom", "data": {}})

        mgr._log_warning.assert_called_once()
        (msg,), _ = mgr._log_warning.call_args
        assert "boom" in msg

    def test_errors_logged_when_gate_on(self) -> None:
        mgr = _manager(log_success=True)
        mgr._log_warning = MagicMock()

        mgr.handle_command({"command": "boom", "data": {}})

        mgr._log_warning.assert_called_once()

    def test_unknown_command_error_logged_when_gate_off(self) -> None:
        """handle_command_not_found — тоже 'неуспех', не 'рутинный успех'."""
        mgr = _manager(log_success=False)
        mgr._log_warning = MagicMock()

        result = mgr.handle_command({"command": "does_not_exist", "data": {}})

        assert result.get("status") == "error"
        mgr._log_warning.assert_called_once()


class TestMetricsUnaffectedByGate:
    """Гейт режет только ЛОГ; статистика (_record_metric) не должна пострадать."""

    def test_success_metric_recorded_when_gate_off(self) -> None:
        mgr = _manager(log_success=False)
        mgr._record_metric = MagicMock()

        mgr.handle_command({"command": "ping", "data": {}})

        names = [call.args[0] for call in mgr._record_metric.call_args_list]
        assert "command_manager.command.execution.success" in names

    def test_success_metric_recorded_when_gate_on(self) -> None:
        mgr = _manager(log_success=True)
        mgr._record_metric = MagicMock()

        mgr.handle_command({"command": "ping", "data": {}})

        names = [call.args[0] for call in mgr._record_metric.call_args_list]
        assert "command_manager.command.execution.success" in names
