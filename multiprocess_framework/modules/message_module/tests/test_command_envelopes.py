# -*- coding: utf-8 -*-
"""Тесты command_envelopes — билдеры формы команд (GUI + driver, один источник правды).

Покрываем:
- build_command_message: форма, data по умолчанию, reply-поля опц., порядок ключей;
- build_system_command_message: process.command-обёртка, targets=ProcessManager, reply-поля;
- регрессия: вывод байт-в-байт совпадает с прежней формой CommandSender (dict-равенство
  + порядок ключей), чтобы рефактор GUI не изменил wire-формат.
"""

from __future__ import annotations

from multiprocess_framework.modules.message_module import (
    build_command_message,
    build_system_command_message,
)


class TestBuildCommandMessage:
    def test_basic_form(self) -> None:
        msg = build_command_message("camera_0", "set_fps", {"fps": 30}, sender="gui")
        assert msg == {
            "type": "command",
            "command": "set_fps",
            "data_type": "set_fps",
            "sender": "gui",
            "targets": ["camera_0"],
            "data": {"fps": 30},
        }

    def test_default_data_empty(self) -> None:
        """args=None → data={}."""
        msg = build_command_message("camera_0", "start", sender="gui")
        assert msg["data"] == {}

    def test_key_order(self) -> None:
        """Порядок ключей фиксирован (важно для байт-в-байт wire-формата)."""
        msg = build_command_message("p", "c", {"x": 1}, sender="s")
        assert list(msg.keys()) == [
            "type",
            "command",
            "data_type",
            "sender",
            "targets",
            "data",
        ]

    def test_reply_fields_omitted_by_default(self) -> None:
        """GUI-путь: reply-поля не добавляются (fire-and-forget)."""
        msg = build_command_message("p", "c", sender="gui")
        assert "request_id" not in msg
        assert "reply_to" not in msg

    def test_reply_fields_present_when_given(self) -> None:
        """Driver-путь: request_id/reply_to добавляются в конец."""
        msg = build_command_message(
            "preprocessor",
            "introspect.handlers",
            {},
            sender="backend_ctl",
            request_id="corr-1",
            reply_to="ProcessManager",
        )
        assert msg["request_id"] == "corr-1"
        assert msg["reply_to"] == "ProcessManager"
        assert list(msg.keys())[-2:] == ["request_id", "reply_to"]


class TestBuildSystemCommandMessage:
    def test_basic_form(self) -> None:
        inner = {"cmd": "process.start", "process_name": "camera"}
        msg = build_system_command_message(inner, sender="gui")
        assert msg == {
            "type": "command",
            "command": "process.command",
            "data_type": "process.command",
            "sender": "gui",
            "targets": ["ProcessManager"],
            "data": inner,
        }

    def test_reply_fields(self) -> None:
        msg = build_system_command_message(
            {"cmd": "process.stop"},
            sender="backend_ctl",
            request_id="corr-9",
            reply_to="ProcessManager",
        )
        assert msg["request_id"] == "corr-9"
        assert msg["reply_to"] == "ProcessManager"

    def test_key_order(self) -> None:
        msg = build_system_command_message({"cmd": "x"}, sender="s")
        assert list(msg.keys()) == [
            "type",
            "command",
            "data_type",
            "sender",
            "targets",
            "data",
        ]


class TestRegressionVsLegacyCommandSenderForm:
    """Вывод билдеров == прежняя inline-форма CommandSender (байт-в-байт)."""

    def test_command_message_identical_to_legacy(self) -> None:
        target, command, args, sender = "camera_0", "set_fps", {"fps": 30}, "gui_process"
        legacy = {
            "type": "command",
            "command": command,
            "data_type": command,
            "sender": sender,
            "targets": [target],
            "data": args or {},
        }
        built = build_command_message(target, command, args, sender=sender)
        assert built == legacy
        assert list(built.keys()) == list(legacy.keys())

    def test_system_command_message_identical_to_legacy(self) -> None:
        command, sender = {"cmd": "process.start", "name": "x"}, "gui_process"
        legacy = {
            "type": "command",
            "command": "process.command",
            "data_type": "process.command",
            "sender": sender,
            "targets": ["ProcessManager"],
            "data": command,
        }
        built = build_system_command_message(command, sender=sender)
        assert built == legacy
        assert list(built.keys()) == list(legacy.keys())
