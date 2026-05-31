# -*- coding: utf-8 -*-
"""Тесты ProcessManagerProxy — тонкого GUI-фасада управления backend (Этап 1).

Проверяют: правильный cmd + Dict at Boundary в send_system_command,
optimistic-ack возврат, fire-and-forget семантику.

Запуск:
    python -m pytest multiprocess_prototype/frontend/bridge/tests/test_process_manager_proxy.py -v
"""

from __future__ import annotations

from multiprocess_prototype.frontend.bridge.process_manager_proxy import ProcessManagerProxy


class _FakeSender:
    """Перехватывает send_system_command для проверки сериализации."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send_system_command(self, command: dict) -> None:
        self.sent.append(command)


def test_replace_blueprint_sends_correct_cmd() -> None:
    sender = _FakeSender()
    proxy = ProcessManagerProxy(sender)
    bp = {"processes": [{"process_name": "p1"}], "wires": []}

    result = proxy.replace_blueprint(bp)

    assert sender.sent == [{"cmd": "blueprint.replace", "blueprint": bp}]
    assert result == {"success": True, "dispatched": True, "cmd": "blueprint.replace"}


def test_process_lifecycle_commands() -> None:
    sender = _FakeSender()
    proxy = ProcessManagerProxy(sender)

    proxy.start_process("cam")
    proxy.stop_process("cam")
    proxy.restart_process("cam")

    assert sender.sent == [
        {"cmd": "process.start", "process_name": "cam"},
        {"cmd": "process.stop", "process_name": "cam"},
        {"cmd": "process.restart", "process_name": "cam"},
    ]


def test_dict_at_boundary() -> None:
    """Аргумент команды — всегда dict (между GUI и backend только dict)."""
    sender = _FakeSender()
    proxy = ProcessManagerProxy(sender)

    proxy.replace_blueprint({"processes": []})

    assert isinstance(sender.sent[0], dict)
