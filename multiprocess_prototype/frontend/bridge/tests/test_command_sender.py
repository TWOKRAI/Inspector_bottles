"""Тесты CommandSender v2 — отправка IPC-команд + debounce.

Тестируем:
- send_command (v1 API): команды НЕ-своему процессу идут через PM-relay
  (process.relay → ProcessManager), свой процесс/PM — напрямую
- send_field_command: immediate и debounce
- send_action_command
- coalescing: несколько быстрых вызовов → одна отправка
- flush: принудительная отправка pending
- request/response: round-trip через router.request

PM-relay: GUI (protected) после hot-swap рецепта держит стейл-копию маршрутов,
поэтому исходящие команды НЕ-своему процессу маршрутизируются через ProcessManager
(всегда свежие очереди). Хелпер ``unwrap`` разворачивает relay-конверт обратно в
адрес+команду, чтобы тесты проверяли смысловой контракт независимо от транспорта.
"""

from __future__ import annotations

from typing import Any

import pytest

from multiprocess_prototype.frontend.bridge.command_sender import CommandSender


# --- Mock Process ---


class MockProcess:
    """Мок GuiProcess — записывает отправленные сообщения."""

    def __init__(self, name: str = "gui") -> None:
        self.name = name
        self.sent: list[tuple[str, dict[str, Any]]] = []

    def send_message(self, target: str, msg: dict[str, Any]) -> None:
        self.sent.append((target, msg))


class MockRouter:
    """Мок RouterManager.request — записывает request-билеты, отдаёт заготовленный ответ."""

    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.requested: list[tuple[dict[str, Any], float]] = []
        self._response = response if response is not None else {"success": True, "result": {}}

    def request(self, msg: dict[str, Any], timeout: float = 5.0) -> dict[str, Any]:
        self.requested.append((msg, timeout))
        return self._response


class MockRequestingProcess(MockProcess):
    """Мок GuiProcess с router_manager (поддержка request/response)."""

    def __init__(self, name: str = "gui", response: dict[str, Any] | None = None) -> None:
        super().__init__(name)
        self.router_manager = MockRouter(response)


def unwrap(entry: tuple[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    """Развернуть PM-relay-конверт обратно в (реальный_адрес, реальный_билет).

    Прямая отправка (свой процесс/PM) возвращается как есть. Relay-конверт
    (target=ProcessManager, command=process.command, data.cmd=process.relay)
    разворачивается в исходный target_process + inner_message.
    """
    target, msg = entry
    if target == "ProcessManager" and msg.get("command") == "process.command":
        data = msg.get("data") or {}
        if data.get("cmd") == "process.relay":
            return data["target_process"], data["inner_message"]
    return target, msg


# --- Fixtures ---


@pytest.fixture
def process() -> MockProcess:
    return MockProcess("gui_process")


@pytest.fixture
def sender(process: MockProcess) -> CommandSender:
    return CommandSender(process)


# --- v1 API: send_command (через PM-relay для не-своих процессов) ---


class TestSendCommand:
    def test_basic_send(self, sender: CommandSender, process: MockProcess) -> None:
        """send_command формирует билет и доставляет его (через relay) целевому процессу."""
        sender.send_command("camera_0", "set_fps", {"fps": 30})

        assert len(process.sent) == 1
        target, msg = unwrap(process.sent[0])
        assert target == "camera_0"
        assert msg["type"] == "command"
        assert msg["command"] == "set_fps"
        assert msg["data_type"] == "set_fps"
        assert msg["sender"] == "gui_process"
        assert msg["targets"] == ["camera_0"]
        assert msg["data"] == {"fps": 30}

    def test_routes_through_pm_relay(self, sender: CommandSender, process: MockProcess) -> None:
        """Команда НЕ-своему процессу идёт конвертом process.relay в ProcessManager."""
        sender.send_command("vision", "register_update", {"register": "hsv_mask", "field": "s_max", "value": 40})

        raw_target, raw_msg = process.sent[0]
        assert raw_target == "ProcessManager"
        assert raw_msg["command"] == "process.command"
        assert raw_msg["data"]["cmd"] == "process.relay"
        assert raw_msg["data"]["target_process"] == "vision"
        inner = raw_msg["data"]["inner_message"]
        assert inner["command"] == "register_update"
        assert inner["data"] == {"register": "hsv_mask", "field": "s_max", "value": 40}

    def test_self_process_direct(self, process: MockProcess) -> None:
        """Команда СВОЕМУ процессу (GUI→GUI) идёт напрямую, без relay."""
        sender = CommandSender(process)
        sender.send_command("gui_process", "noop", {})

        raw_target, raw_msg = process.sent[0]
        assert raw_target == "gui_process"
        assert raw_msg["command"] == "noop"

    def test_process_manager_direct(self, sender: CommandSender, process: MockProcess) -> None:
        """Команда самому ProcessManager идёт напрямую (его очередь стабильна)."""
        sender.send_command("ProcessManager", "system.stats", {})

        raw_target, raw_msg = process.sent[0]
        assert raw_target == "ProcessManager"
        assert raw_msg["command"] == "system.stats"

    def test_send_without_args(self, sender: CommandSender, process: MockProcess) -> None:
        """send_command без args → data = {}."""
        sender.send_command("camera_0", "start")
        _, msg = unwrap(process.sent[0])
        assert msg["data"] == {}

    def test_multiple_sends(self, sender: CommandSender, process: MockProcess) -> None:
        """Несколько вызовов → несколько сообщений."""
        sender.send_command("proc_1", "cmd_a")
        sender.send_command("proc_2", "cmd_b")
        assert len(process.sent) == 2
        targets = {unwrap(e)[0] for e in process.sent}
        assert targets == {"proc_1", "proc_2"}


# --- v2: send_field_command ---


class TestSendFieldCommand:
    def test_immediate_send(self, sender: CommandSender, process: MockProcess) -> None:
        """debounce_ms=0 → немедленная отправка."""
        sender.send_field_command("processor_0", "set_config", {"h_min": 50})

        assert len(process.sent) == 1
        _, msg = unwrap(process.sent[0])
        assert msg["command"] == "set_config"
        assert msg["data"] == {"h_min": 50}

    def test_debounce_stores_pending_then_flush(self, sender: CommandSender, process: MockProcess) -> None:
        """debounce_ms > 0 → данные в pending, flush отправляет."""
        sender.send_field_command("processor_0", "set_config", {"h_min": 50}, debounce_ms=50)
        # QTimer запущен, но event loop не крутится — данные в pending или уже flush'нуты
        # Принудительный flush гарантирует отправку
        sender.flush()
        assert len(process.sent) >= 1
        _, msg = unwrap(process.sent[-1])
        assert msg["data"] == {"h_min": 50}

    def test_coalescing(self, sender: CommandSender, process: MockProcess) -> None:
        """Несколько вызовов для одного поля → последнее значение."""
        # Вручную заполняем pending (имитация debounce без Qt)
        sender._pending[("proc", "set_config", "h_min")] = 10
        sender._pending[("proc", "set_config", "h_min")] = 50  # перезапись
        sender._pending[("proc", "set_config", "h_max")] = 180

        sender._flush_pending()

        assert len(process.sent) == 1
        _, msg = unwrap(process.sent[0])
        assert msg["data"] == {"h_min": 50, "h_max": 180}

    def test_coalescing_different_targets(self, sender: CommandSender, process: MockProcess) -> None:
        """Pending для разных targets → отдельные сообщения."""
        sender._pending[("proc_1", "cmd_a", "field")] = 1
        sender._pending[("proc_2", "cmd_b", "field")] = 2

        sender._flush_pending()

        assert len(process.sent) == 2
        targets = {unwrap(e)[0] for e in process.sent}
        assert targets == {"proc_1", "proc_2"}

    def test_flush_clears_pending(self, sender: CommandSender) -> None:
        """flush() очищает pending."""
        sender._pending[("p", "c", "f")] = 1
        sender.flush()
        assert sender.pending_count == 0

    def test_flush_empty_noop(self, sender: CommandSender, process: MockProcess) -> None:
        """flush() при пустом pending — ничего не отправляется."""
        sender.flush()
        assert len(process.sent) == 0


# --- v2: send_action_command ---


class TestSendActionCommand:
    def test_action_immediate(self, sender: CommandSender, process: MockProcess) -> None:
        """Action-команда всегда отправляется немедленно."""
        sender.send_action_command("camera_0", "start_capture")

        assert len(process.sent) == 1
        _, msg = unwrap(process.sent[0])
        assert msg["command"] == "start_capture"
        assert msg["data"] == {}

    def test_action_with_args(self, sender: CommandSender, process: MockProcess) -> None:
        """Action-команда с аргументами."""
        sender.send_action_command("camera_0", "set_resolution", {"w": 1920, "h": 1080})

        _, msg = unwrap(process.sent[0])
        assert msg["data"] == {"w": 1920, "h": 1080}


# --- request/response (command-result-bridge) ---


class TestRequestCommand:
    """request_command/request_system_command — round-trip через router.request."""

    def test_request_system_command_returns_real_response(self) -> None:
        """request_system_command идёт в router.request и возвращает реальный ответ."""
        process = MockRequestingProcess("gui", response={"success": True, "result": {"replaced": ["w1"]}})
        sender = CommandSender(process)

        resp = sender.request_system_command({"cmd": "topology.apply", "topology_dict": {"processes": []}})

        # Билет ушёл в router.request, НЕ в fire-and-forget send_message
        assert len(process.router_manager.requested) == 1
        assert len(process.sent) == 0
        msg, _timeout = process.router_manager.requested[0]
        assert msg["command"] == "process.command"
        assert msg["data"] == {"cmd": "topology.apply", "topology_dict": {"processes": []}}
        assert msg["sender"] == "gui"
        # Реальный ответ проброшен наверх
        assert resp == {"success": True, "result": {"replaced": ["w1"]}}

    def test_request_command_returns_real_response(self) -> None:
        """request_command (прямая команда процессу) тоже round-trip."""
        process = MockRequestingProcess("gui", response={"success": True, "result": "ok"})
        sender = CommandSender(process)

        resp = sender.request_command("camera_0", "process.stop", {"process_name": "camera_0"})

        msg, _ = process.router_manager.requested[0]
        assert msg["command"] == "process.stop"
        assert msg["targets"] == ["camera_0"]
        assert resp["result"] == "ok"

    def test_request_passes_timeout(self) -> None:
        """timeout прокидывается в router.request."""
        process = MockRequestingProcess("gui")
        sender = CommandSender(process)

        sender.request_system_command({"cmd": "process.start"}, timeout=12.5)

        _, timeout = process.router_manager.requested[0]
        assert timeout == 12.5

    def test_request_default_timeout(self) -> None:
        """Без явного timeout — DEFAULT_REQUEST_TIMEOUT."""
        from multiprocess_prototype.frontend.bridge.command_sender import DEFAULT_REQUEST_TIMEOUT

        process = MockRequestingProcess("gui")
        sender = CommandSender(process)

        sender.request_system_command({"cmd": "process.start"})

        _, timeout = process.router_manager.requested[0]
        assert timeout == DEFAULT_REQUEST_TIMEOUT

    def test_request_without_router_raises(self) -> None:
        """Процесс без router_manager → понятная ошибка конфигурации (не тихий сбой)."""
        process = MockProcess("gui")  # без router_manager
        sender = CommandSender(process)

        with pytest.raises(RuntimeError, match="router_manager"):
            sender.request_system_command({"cmd": "process.start"})

    def test_fire_and_forget_unchanged_by_request_path(self) -> None:
        """send_command остаётся fire-and-forget (через send_message, не router.request)."""
        process = MockRequestingProcess("gui")
        sender = CommandSender(process)

        sender.send_command("camera_0", "set_fps", {"fps": 30})

        assert len(process.sent) == 1
        assert len(process.router_manager.requested) == 0
        _, msg = unwrap(process.sent[0])
        assert msg["command"] == "set_fps"


# --- pending_count ---


class TestPendingCount:
    def test_pending_count_empty(self, sender: CommandSender) -> None:
        assert sender.pending_count == 0

    def test_pending_count_after_add(self, sender: CommandSender) -> None:
        sender._pending[("p", "c", "f1")] = 1
        sender._pending[("p", "c", "f2")] = 2
        assert sender.pending_count == 2
