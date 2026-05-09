"""Тесты CommandSender v2 — отправка IPC-команд + debounce.

Тестируем:
- send_command (v1 API, обратная совместимость)
- send_field_command: immediate и debounce
- send_action_command
- coalescing: несколько быстрых вызовов → одна отправка
- flush: принудительная отправка pending
"""

from __future__ import annotations

from typing import Any

import pytest

from multiprocess_prototype_2.frontend.bridge.command_sender import CommandSender


# --- Mock Process ---


class MockProcess:
    """Мок GuiProcess — записывает отправленные сообщения."""

    def __init__(self, name: str = "gui") -> None:
        self.name = name
        self.sent: list[tuple[str, dict[str, Any]]] = []

    def send_message(self, target: str, msg: dict[str, Any]) -> None:
        self.sent.append((target, msg))


# --- Fixtures ---


@pytest.fixture
def process() -> MockProcess:
    return MockProcess("gui_process")


@pytest.fixture
def sender(process: MockProcess) -> CommandSender:
    return CommandSender(process)


# --- v1 API (обратная совместимость) ---


class TestSendCommand:

    def test_basic_send(self, sender: CommandSender, process: MockProcess) -> None:
        """send_command формирует и отправляет dict-сообщение."""
        sender.send_command("camera_0", "set_fps", {"fps": 30})

        assert len(process.sent) == 1
        target, msg = process.sent[0]
        assert target == "camera_0"
        assert msg["type"] == "command"
        assert msg["command"] == "set_fps"
        assert msg["data_type"] == "set_fps"
        assert msg["sender"] == "gui_process"
        assert msg["targets"] == ["camera_0"]
        assert msg["data"] == {"fps": 30}

    def test_send_without_args(self, sender: CommandSender, process: MockProcess) -> None:
        """send_command без args → data = {}."""
        sender.send_command("camera_0", "start")
        _, msg = process.sent[0]
        assert msg["data"] == {}

    def test_multiple_sends(self, sender: CommandSender, process: MockProcess) -> None:
        """Несколько вызовов → несколько сообщений."""
        sender.send_command("proc_1", "cmd_a")
        sender.send_command("proc_2", "cmd_b")
        assert len(process.sent) == 2


# --- v2: send_field_command ---


class TestSendFieldCommand:

    def test_immediate_send(self, sender: CommandSender, process: MockProcess) -> None:
        """debounce_ms=0 → немедленная отправка."""
        sender.send_field_command("processor_0", "set_config", {"h_min": 50})

        assert len(process.sent) == 1
        _, msg = process.sent[0]
        assert msg["command"] == "set_config"
        assert msg["data"] == {"h_min": 50}

    def test_debounce_stores_pending_then_flush(self, sender: CommandSender, process: MockProcess) -> None:
        """debounce_ms > 0 → данные в pending, flush отправляет."""
        sender.send_field_command(
            "processor_0", "set_config", {"h_min": 50}, debounce_ms=50
        )
        # QTimer запущен, но event loop не крутится — данные в pending или уже flush'нуты
        # Принудительный flush гарантирует отправку
        sender.flush()
        assert len(process.sent) >= 1
        _, msg = process.sent[-1]
        assert msg["data"] == {"h_min": 50}

    def test_coalescing(self, sender: CommandSender, process: MockProcess) -> None:
        """Несколько вызовов для одного поля → последнее значение."""
        # Вручную заполняем pending (имитация debounce без Qt)
        sender._pending[("proc", "set_config", "h_min")] = 10
        sender._pending[("proc", "set_config", "h_min")] = 50  # перезапись
        sender._pending[("proc", "set_config", "h_max")] = 180

        sender._flush_pending()

        assert len(process.sent) == 1
        _, msg = process.sent[0]
        assert msg["data"] == {"h_min": 50, "h_max": 180}

    def test_coalescing_different_targets(self, sender: CommandSender, process: MockProcess) -> None:
        """Pending для разных targets → отдельные сообщения."""
        sender._pending[("proc_1", "cmd_a", "field")] = 1
        sender._pending[("proc_2", "cmd_b", "field")] = 2

        sender._flush_pending()

        assert len(process.sent) == 2
        targets = {t for t, _ in process.sent}
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
        _, msg = process.sent[0]
        assert msg["command"] == "start_capture"
        assert msg["data"] == {}

    def test_action_with_args(self, sender: CommandSender, process: MockProcess) -> None:
        """Action-команда с аргументами."""
        sender.send_action_command("camera_0", "set_resolution", {"w": 1920, "h": 1080})

        _, msg = process.sent[0]
        assert msg["data"] == {"w": 1920, "h": 1080}


# --- pending_count ---


class TestPendingCount:

    def test_pending_count_empty(self, sender: CommandSender) -> None:
        assert sender.pending_count == 0

    def test_pending_count_after_add(self, sender: CommandSender) -> None:
        sender._pending[("p", "c", "f1")] = 1
        sender._pending[("p", "c", "f2")] = 2
        assert sender.pending_count == 2
