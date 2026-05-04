"""Unit-тесты Фазы 4 конструктора — конвертер wires (чистые, без Qt).

Тестируемые функции:
- diff_wire_configs  — вычисление diff между текущим и желаемым состоянием wires
- extract_wire_commands — генерация IPC-команд из diff

Все тесты чистые (без Qt/PySide6).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_V3_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT, _V3_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multiprocess_prototype.registers.system_topology.converters import (
    diff_wire_configs,
    extract_wire_commands,
)


# ---------------------------------------------------------------------------
# Тестовые данные
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

WIRE_2 = {
    "source": "processor_0.resize.frame",
    "target": "renderer_0.render.frame",
    "transport": "router",
    "description": "proc → render",
    "shm_config": {},
}


# ---------------------------------------------------------------------------
# diff_wire_configs — added
# ---------------------------------------------------------------------------


def test_diff_added():
    """current без wires, desired с 2 wires → wires_added содержит оба ключа."""
    current = {"wires": {}}
    desired = {"wires": {"w1": WIRE_1, "w2": WIRE_2}}
    diff = diff_wire_configs(current, desired)
    assert set(diff["wires_added"]) == {"w1", "w2"}
    assert diff["wires_removed"] == []
    assert diff["wires_modified"] == []
    assert diff["has_changes"] is True


def test_diff_removed():
    """current с wire, desired без → wires_removed содержит ключ."""
    current = {"wires": {"w1": WIRE_1}}
    desired = {"wires": {}}
    diff = diff_wire_configs(current, desired)
    assert "w1" in diff["wires_removed"]
    assert diff["wires_added"] == []
    assert diff["has_changes"] is True


def test_diff_modified_transport():
    """Изменённый transport (router→direct) → wires_modified содержит ключ."""
    wire_modified = dict(WIRE_1)
    wire_modified["transport"] = "direct"
    current = {"wires": {"w1": WIRE_1}}
    desired = {"wires": {"w1": wire_modified}}
    diff = diff_wire_configs(current, desired)
    assert "w1" in diff["wires_modified"]
    assert diff["has_changes"] is True


def test_diff_modified_shm_config():
    """Изменённый buffer_slots в shm_config → wires_modified содержит ключ."""
    wire_modified = dict(WIRE_1)
    wire_modified["shm_config"] = dict(WIRE_1["shm_config"])
    wire_modified["shm_config"]["buffer_slots"] = 8
    current = {"wires": {"w1": WIRE_1}}
    desired = {"wires": {"w1": wire_modified}}
    diff = diff_wire_configs(current, desired)
    assert "w1" in diff["wires_modified"]
    assert diff["has_changes"] is True


def test_diff_no_changes():
    """Одинаковые данные → has_changes=False, все списки пустые."""
    state = {"wires": {"w1": WIRE_1, "w2": WIRE_2}}
    diff = diff_wire_configs(state, state)
    assert diff["has_changes"] is False
    assert diff["wires_added"] == []
    assert diff["wires_removed"] == []
    assert diff["wires_modified"] == []


def test_diff_from_none():
    """current=None → все wires в desired попадают в wires_added."""
    desired = {"wires": {"w1": WIRE_1, "w2": WIRE_2}}
    diff = diff_wire_configs(None, desired)
    assert set(diff["wires_added"]) == {"w1", "w2"}
    assert diff["has_changes"] is True


# ---------------------------------------------------------------------------
# extract_wire_commands — setup для добавленных
# ---------------------------------------------------------------------------


def test_commands_setup_for_added():
    """Добавленный wire → cmd='wire.setup' с полными полями."""
    current = {"wires": {}}
    desired = {"wires": {"w1": WIRE_1}}
    commands = extract_wire_commands(current, desired)
    assert len(commands) == 1
    cmd = commands[0]
    assert cmd["cmd"] == "wire.setup"
    assert cmd["wire_key"] == "w1"
    assert cmd["source"] == WIRE_1["source"]
    assert cmd["target"] == WIRE_1["target"]
    assert cmd["transport"] == WIRE_1["transport"]
    assert cmd["source_process"] == "camera_0"
    assert cmd["target_process"] == "processor_0"
    assert "shm_config" in cmd


def test_commands_teardown_for_removed():
    """Удалённый wire → cmd='wire.teardown'."""
    current = {"wires": {"w1": WIRE_1}}
    desired = {"wires": {}}
    commands = extract_wire_commands(current, desired)
    assert len(commands) == 1
    cmd = commands[0]
    assert cmd["cmd"] == "wire.teardown"
    assert cmd["wire_key"] == "w1"
    assert cmd["source_process"] == "camera_0"
    assert cmd["target_process"] == "processor_0"


def test_commands_order_teardown_before_setup():
    """При наличии removed и added: teardown идёт перед setup."""
    current = {"wires": {"w1": WIRE_1}}
    desired = {"wires": {"w2": WIRE_2}}
    commands = extract_wire_commands(current, desired)
    cmds = [c["cmd"] for c in commands]
    assert "wire.teardown" in cmds
    assert "wire.setup" in cmds
    teardown_idx = cmds.index("wire.teardown")
    setup_idx = cmds.index("wire.setup")
    assert teardown_idx < setup_idx


def test_commands_modified_teardown_then_setup():
    """Изменённый wire → teardown старого + setup нового."""
    wire_v2 = dict(WIRE_1)
    wire_v2["transport"] = "direct"
    current = {"wires": {"w1": WIRE_1}}
    desired = {"wires": {"w1": wire_v2}}
    commands = extract_wire_commands(current, desired)
    cmds = [c["cmd"] for c in commands]
    assert cmds.count("wire.teardown") == 1
    assert cmds.count("wire.setup") == 1
    # teardown идёт до setup
    assert cmds.index("wire.teardown") < cmds.index("wire.setup")
    # Оба относятся к одному wire_key
    assert all(c["wire_key"] == "w1" for c in commands)


def test_commands_auto_shm_name():
    """Wire без shm_name → авто-генерация '{wire_key}_shm'."""
    wire_no_shm = dict(WIRE_2)  # shm_config = {}
    current = {"wires": {}}
    desired = {"wires": {"my_wire": wire_no_shm}}
    commands = extract_wire_commands(current, desired)
    assert len(commands) == 1
    shm_config = commands[0]["shm_config"]
    assert shm_config["shm_name"] == "my_wire_shm"


def test_commands_auto_owner():
    """Wire без owner_process → авто-присвоение source_process."""
    wire_no_owner = dict(WIRE_2)  # shm_config = {}
    current = {"wires": {}}
    desired = {"wires": {"w2": wire_no_owner}}
    commands = extract_wire_commands(current, desired)
    shm_config = commands[0]["shm_config"]
    # source = "processor_0.resize.frame" → source_process = "processor_0"
    assert shm_config["owner_process"] == "processor_0"


def test_commands_empty():
    """Нет изменений → пустой список команд."""
    state = {"wires": {"w1": WIRE_1}}
    commands = extract_wire_commands(state, state)
    assert commands == []


def test_commands_from_none():
    """current=None → setup для всех wires в desired."""
    desired = {"wires": {"w1": WIRE_1, "w2": WIRE_2}}
    commands = extract_wire_commands(None, desired)
    assert all(c["cmd"] == "wire.setup" for c in commands)
    wire_keys = {c["wire_key"] for c in commands}
    assert wire_keys == {"w1", "w2"}
