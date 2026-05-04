"""Unit-тесты Фазы 4 конструктора — TopologyBridge (wires) + WireDataBridge.

Проверяем:
- TopologyBridge._apply_wires: команды отправляются при наличии wires
- TopologyBridge._apply_wires: graceful skip при command_handler=None
- TopologyBridge._apply_wires: пустые wires → нет команд
- TopologyBridge.apply(None): wires включены в полный apply
- TopologyBridge.apply: второй вызов без изменений → 0 wire-команд
- WireDataBridge.get_status: дефолт NOT_APPLIED для неизвестного wire
- WireDataBridge.on_apply_started: ставит статус PENDING
- WireDataBridge.on_apply_completed: переводит в целевой статус (IDLE)
- WireDataBridge.statuses_changed: сигнал испускается при изменении
- WireDataBridge.get_all_statuses: возвращает копию словаря
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_V3_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT, _V3_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multiprocess_prototype.frontend.bridges.topology_bridge import TopologyBridge
from multiprocess_prototype.frontend.bridges.wire_data_bridge import (
    WireDataBridge,
    WireStatus,
)
from multiprocess_prototype.frontend.models.system_topology_editor import (
    SystemTopologyEditor,
)
from multiprocess_prototype.registers.system_topology.schemas import (
    SECTION_WIRES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

WIRE_1 = {
    "source": "camera_0.capture.frame",
    "target": "processor_0.color_mask.frame",
    "transport": "router",
    "description": "cam → proc",
    "shm_config": {
        "shm_name": "cam_to_proc",
        "buffer_slots": 4,
        "owner_process": "camera_0",
        "strategy": "direct",
    },
}


class MockCommandHandler:
    """Мок command_handler — записывает вызовы send()."""

    def __init__(self):
        self.sent: list[dict] = []

    def send(self, channel: str, data=None) -> bool:
        self.sent.append({"channel": channel, "data": data})
        return True


def _make_editor_with_wire() -> SystemTopologyEditor:
    """Создать SystemTopologyEditor с одним wire и нужными процессами.

    Валидация wires проверяет FK — процессы source/target должны существовать,
    а плагины из адреса должны быть в списке plugins процесса.
    """
    editor = SystemTopologyEditor()
    # Добавляем процессы, на которые ссылается WIRE_1:
    # source="camera_0.capture.frame" → процесс camera_0, плагин capture
    # target="processor_0.color_mask.frame" → процесс processor_0, плагин color_mask
    editor._data["processes"]["camera_0"] = {
        "name": "camera_0",
        "class_path": "pkg.CameraProcess",
        "priority": "normal",
        "auto_start": True,
        "sort_order": 0,
        "plugins": [{"plugin_class": "CapturePlugin", "plugin_name": "capture"}],
    }
    editor._data["processes"]["processor_0"] = {
        "name": "processor_0",
        "class_path": "pkg.ProcessorProcess",
        "priority": "normal",
        "auto_start": True,
        "sort_order": 1,
        "plugins": [{"plugin_class": "ColorMaskPlugin", "plugin_name": "color_mask"}],
    }
    editor._data["wires"]["w1"] = WIRE_1
    return editor


def _make_editor_empty() -> SystemTopologyEditor:
    """Создать пустой SystemTopologyEditor."""
    return SystemTopologyEditor()


def _make_mock_rm():
    """Мок registers_manager."""
    rm = MagicMock()
    rm.set_field_value.return_value = (True, None)
    return rm


def _make_mock_wm():
    """Мок window_manager."""
    wm = MagicMock()
    wm.list_windows.return_value = []
    return wm


# ---------------------------------------------------------------------------
# Тесты TopologyBridge — wires
# ---------------------------------------------------------------------------


def test_apply_wires_sends_commands():
    """apply(SECTION_WIRES) с wire в editor → команды wire.setup отправлены."""
    editor = _make_editor_with_wire()
    cmd = MockCommandHandler()
    bridge = TopologyBridge(editor, command_handler=cmd)

    result = bridge.apply(SECTION_WIRES)

    assert result is True
    assert len(cmd.sent) > 0
    # Должна быть команда wire.setup
    setup_cmds = [s for s in cmd.sent if s["data"] and s["data"].get("cmd") == "wire.setup"]
    assert len(setup_cmds) == 1
    assert setup_cmds[0]["data"]["wire_key"] == "w1"


def test_apply_wires_no_handler():
    """apply(SECTION_WIRES) при command_handler=None → True (graceful skip)."""
    editor = _make_editor_with_wire()
    bridge = TopologyBridge(editor, command_handler=None)

    result = bridge.apply(SECTION_WIRES)

    assert result is True


def test_apply_wires_empty():
    """apply(SECTION_WIRES) при пустых wires → нет команд."""
    editor = _make_editor_empty()
    cmd = MockCommandHandler()
    bridge = TopologyBridge(editor, command_handler=cmd)

    bridge.apply(SECTION_WIRES)

    # Нет wire-команд (допустимы другие категории, но wire.setup/teardown — нет)
    wire_cmds = [
        s for s in cmd.sent
        if s["data"] and s["data"].get("cmd", "").startswith("wire.")
    ]
    assert len(wire_cmds) == 0


def test_apply_all_includes_wires():
    """apply(None) включает wire-команды в полный apply."""
    editor = _make_editor_with_wire()
    # _validate_processes требует protected-воркера для каждого процесса
    editor._data["workers"]["camera_0_main"] = {
        "process_ref": "camera_0", "name": "main",
        "worker_type": "router_poll", "enabled": True,
        "protected": True, "target_interval_ms": 0, "sort_order": 0,
    }
    editor._data["workers"]["processor_0_main"] = {
        "process_ref": "processor_0", "name": "main",
        "worker_type": "router_poll", "enabled": True,
        "protected": True, "target_interval_ms": 0, "sort_order": 0,
    }
    cmd = MockCommandHandler()
    rm = _make_mock_rm()
    wm = _make_mock_wm()
    bridge = TopologyBridge(editor, command_handler=cmd, registers_manager=rm, window_manager=wm)

    result = bridge.apply(None)

    assert result is True
    wire_cmds = [
        s for s in cmd.sent
        if s["data"] and s["data"].get("cmd", "").startswith("wire.")
    ]
    assert len(wire_cmds) > 0


def test_apply_wires_second_call_no_diff():
    """Второй apply(SECTION_WIRES) без изменений → 0 wire-команд."""
    editor = _make_editor_with_wire()
    cmd = MockCommandHandler()
    bridge = TopologyBridge(editor, command_handler=cmd)

    # Первый apply: wire.setup отправлен, current обновлён
    bridge.apply(SECTION_WIRES)
    count_after_first = len(cmd.sent)

    # Второй apply: данные не изменились → diff пустой → команд нет
    bridge.apply(SECTION_WIRES)
    count_after_second = len(cmd.sent)

    assert count_after_second == count_after_first


# ---------------------------------------------------------------------------
# Тесты WireDataBridge (требуют Qt)
# ---------------------------------------------------------------------------


@pytest.fixture
def wire_bridge(qapp):
    """Экземпляр WireDataBridge без внешних зависимостей."""
    return WireDataBridge(command_handler=None, topology_editor=None)


def test_default_status_not_applied(wire_bridge):
    """Неизвестный wire → get_status возвращает NOT_APPLIED."""
    status = wire_bridge.get_status("w1")
    assert status == WireStatus.NOT_APPLIED


def test_on_apply_started_pending(wire_bridge):
    """on_apply_started(["w1"]) → get_status("w1") == PENDING."""
    wire_bridge.on_apply_started(["w1"])
    assert wire_bridge.get_status("w1") == WireStatus.PENDING


def test_on_apply_completed(wire_bridge):
    """on_apply_completed({"w1": "idle"}) → get_status("w1") == IDLE."""
    wire_bridge.on_apply_started(["w1"])
    wire_bridge.on_apply_completed({"w1": "idle"})
    assert wire_bridge.get_status("w1") == WireStatus.IDLE


def test_statuses_changed_signal(qapp):
    """on_apply_started → сигнал statuses_changed испускается."""
    bridge = WireDataBridge(command_handler=None, topology_editor=None)
    received: list[dict] = []
    bridge.statuses_changed.connect(lambda d: received.append(d))

    bridge.on_apply_started(["w1"])

    assert len(received) == 1
    assert "w1" in received[0]
    assert received[0]["w1"] == WireStatus.PENDING


def test_get_all_statuses(wire_bridge):
    """get_all_statuses возвращает копию словаря, а не ссылку."""
    wire_bridge.on_apply_started(["w1", "w2"])
    statuses = wire_bridge.get_all_statuses()

    # Изменение копии не влияет на оригинал
    statuses["w1"] = WireStatus.BROKEN
    assert wire_bridge.get_status("w1") == WireStatus.PENDING
