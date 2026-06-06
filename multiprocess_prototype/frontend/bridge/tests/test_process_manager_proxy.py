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


def test_shutdown_system_sends_correct_cmd() -> None:
    sender = _FakeSender()
    proxy = ProcessManagerProxy(sender)

    result = proxy.shutdown_system()

    assert sender.sent == [{"cmd": "system.shutdown"}]
    assert result == {"success": True, "dispatched": True, "cmd": "system.shutdown"}


def test_dict_at_boundary() -> None:
    """Аргумент команды — всегда dict (между GUI и backend только dict)."""
    sender = _FakeSender()
    proxy = ProcessManagerProxy(sender)

    proxy.replace_blueprint({"processes": []})

    assert isinstance(sender.sent[0], dict)


# --- request/response async (command-result-bridge P2) ---


class _FakeRequestingSender(_FakeSender):
    """Fake-sender с request_system_command (round-trip), отдаёт заготовленный результат."""

    def __init__(self, response: dict | None = None) -> None:
        super().__init__()
        self.requested: list[dict] = []
        self._response = response if response is not None else {"success": True, "result": {}}

    def request_system_command(self, command: dict, *, timeout: float = 30.0) -> dict:
        self.requested.append(command)
        return self._response


def test_replace_blueprint_async_delivers_real_result(qtbot) -> None:
    """replace_blueprint_async идёт через request_system_command, реальный результат в on_result."""
    sender = _FakeRequestingSender(response={"success": True, "result": {"replaced": ["p1"]}})
    proxy = ProcessManagerProxy(sender)
    bp = {"processes": [{"process_name": "p1"}], "wires": []}
    results: list[dict] = []

    proxy.replace_blueprint_async(bp, results.append)

    qtbot.waitUntil(lambda: len(results) == 1, timeout=2000)
    # Ушло через request (round-trip), НЕ через fire-and-forget send_system_command
    assert sender.requested == [{"cmd": "blueprint.replace", "blueprint": bp}]
    assert sender.sent == []
    assert results[0] == {"success": True, "result": {"replaced": ["p1"]}}


def test_lifecycle_async_commands(qtbot) -> None:
    """start/stop/restart_process_async идут round-trip с результатом.

    Порядок НЕ проверяем: async-сабмиты исполняются на пуле конкурентно
    (RequestRunner), порядок завершения не гарантирован — сравниваем как множество.
    """
    sender = _FakeRequestingSender(response={"success": True, "result": "ok"})
    proxy = ProcessManagerProxy(sender)
    results: list[dict] = []

    proxy.start_process_async("cam", results.append)
    proxy.stop_process_async("cam", results.append)
    proxy.restart_process_async("cam", results.append)

    qtbot.waitUntil(lambda: len(results) == 3, timeout=2000)
    requested_cmds = {c["cmd"] for c in sender.requested}
    assert requested_cmds == {"process.start", "process.stop", "process.restart"}
    assert all(c["process_name"] == "cam" for c in sender.requested)
    assert all(r == {"success": True, "result": "ok"} for r in results)


def test_async_error_delivers_error_result(qtbot) -> None:
    """Ошибка request → error-result в on_result (не падение)."""

    class _BoomSender(_FakeSender):
        def request_system_command(self, command: dict, *, timeout: float = 30.0) -> dict:
            raise RuntimeError("no backend")

    proxy = ProcessManagerProxy(_BoomSender())
    results: list[dict] = []

    proxy.replace_blueprint_async({"processes": []}, results.append)

    qtbot.waitUntil(lambda: len(results) == 1, timeout=2000)
    assert results[0]["success"] is False
    assert "no backend" in results[0]["error"]


def test_fire_and_forget_methods_unchanged(qtbot) -> None:
    """Старые fire-and-forget методы не задеты async-путём (паритет, G5)."""
    sender = _FakeRequestingSender()
    proxy = ProcessManagerProxy(sender)

    proxy.replace_blueprint({"processes": []})

    assert sender.sent == [{"cmd": "blueprint.replace", "blueprint": {"processes": []}}]
    assert sender.requested == []
