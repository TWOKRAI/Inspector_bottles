"""Parity-тест: YAML-протокол робота ↔ Python-карта.

Инвариант: YAML-файл delta_universal3.yaml описывает ровно ту же карту
регистров, что build_register_map(word_order="little") в core/registers.py.

Проверяется:
- Множество имён совпадает.
- word_order == "little".
- Для каждой Reg-записи: address, scale, signed.
- Для каждой RegDW-записи: address, signed.
- Для каждой RegBlock-записи: address, count, имена полей, scale и signed полей.
- write_ops с одинаковым dict дают идентичные ops у обеих карт.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from Services.modbus.core.protocol_file import load_protocol
from Services.modbus.core.register_map import Reg, RegBlock, RegDW
from Services.robot_comm.core.registers import build_register_map

_PROTO_PATH = Path(__file__).resolve().parents[1] / "protocols" / "delta_universal3.yaml"
_PY_MAP = build_register_map(word_order="little")


@pytest.fixture(scope="module")
def robot_proto():
    """Загруженный YAML-протокол delta_universal3."""
    return load_protocol(_PROTO_PATH)


# ─────────────────────── базовые инварианты ─────────────────────────────────── #


def test_robot_names_match(robot_proto) -> None:
    """Множество имён записей YAML == build_register_map('little')."""
    yaml_names = set(robot_proto.register_map.names())
    py_names = set(_PY_MAP.names())
    assert yaml_names == py_names, (
        f"Лишние в YAML: {yaml_names - py_names}, отсутствуют в YAML: {py_names - yaml_names}"
    )


def test_robot_word_order(robot_proto) -> None:
    """word_order в YAML == 'little' (как у Python-карты)."""
    assert robot_proto.register_map.word_order == "little"
    assert robot_proto.register_map.word_order == _PY_MAP.word_order


# ─────────────────────── Reg-записи ─────────────────────────────────────────── #


@pytest.mark.parametrize(
    "name",
    [
        "mode",
        "job_flag",
        "job_x",
        "job_y",
        "stop",
        "servo",
        "free",
        "cfg_flag",
        "draw_flag",
        "draw_type",
        "draw_count",
        "draw_busy",
        "draw_prog",
        "draw_abort",
        "circ_cx",
        "circ_cy",
        "circ_r",
        "pen_down",
        "pen_up",
        "draw_spd",
        "overlap",
    ],
)
def test_robot_reg_address_scale_signed(robot_proto, name: str) -> None:
    """Reg-записи: address/scale/signed совпадают 1:1."""
    yaml_entry = robot_proto.register_map.entry(name)
    py_entry = _PY_MAP.entry(name)
    assert isinstance(yaml_entry, Reg), f"{name}: ожидается Reg в YAML"
    assert isinstance(py_entry, Reg), f"{name}: ожидается Reg в Python-карте"
    assert yaml_entry.address == py_entry.address, f"{name}: address"
    assert yaml_entry.scale == py_entry.scale, f"{name}: scale"
    assert yaml_entry.signed == py_entry.signed, f"{name}: signed"


# ─────────────────────── RegDW-записи ───────────────────────────────────────── #


@pytest.mark.parametrize("name", ["job_ecap", "encoder"])
def test_robot_dw_address_signed(robot_proto, name: str) -> None:
    """RegDW-записи: address и signed совпадают."""
    yaml_entry = robot_proto.register_map.entry(name)
    py_entry = _PY_MAP.entry(name)
    assert isinstance(yaml_entry, RegDW), f"{name}: ожидается RegDW в YAML"
    assert isinstance(py_entry, RegDW), f"{name}: ожидается RegDW в Python-карте"
    assert yaml_entry.address == py_entry.address, f"{name}: address"
    assert yaml_entry.signed == py_entry.signed, f"{name}: signed"


# ─────────────────────── RegBlock-записи ────────────────────────────────────── #


@pytest.mark.parametrize("name", ["echo", "telemetry", "config"])
def test_robot_block_address_count(robot_proto, name: str) -> None:
    """RegBlock-записи: address и count совпадают."""
    yaml_entry = robot_proto.register_map.entry(name)
    py_entry = _PY_MAP.entry(name)
    assert isinstance(yaml_entry, RegBlock), f"{name}: ожидается RegBlock в YAML"
    assert isinstance(py_entry, RegBlock), f"{name}: ожидается RegBlock в Python-карте"
    assert yaml_entry.address == py_entry.address, f"{name}: address"
    assert yaml_entry.count == py_entry.count, f"{name}: count"


@pytest.mark.parametrize("name", ["echo", "telemetry", "config"])
def test_robot_block_field_names_ordered(robot_proto, name: str) -> None:
    """RegBlock: имена полей совпадают в правильном порядке."""
    yaml_entry = robot_proto.register_map.entry(name)
    py_entry = _PY_MAP.entry(name)
    assert isinstance(yaml_entry, RegBlock)
    assert isinstance(py_entry, RegBlock)
    yaml_names = [f.name for f in yaml_entry.fields]
    py_names = [f.name for f in py_entry.fields]
    assert yaml_names == py_names, f"блок {name!r}: порядок полей"


@pytest.mark.parametrize("name", ["echo", "telemetry", "config"])
def test_robot_block_field_scale_signed(robot_proto, name: str) -> None:
    """RegBlock: scale и signed каждого поля совпадают."""
    yaml_entry = robot_proto.register_map.entry(name)
    py_entry = _PY_MAP.entry(name)
    assert isinstance(yaml_entry, RegBlock)
    assert isinstance(py_entry, RegBlock)
    for yaml_f, py_f in zip(yaml_entry.fields, py_entry.fields, strict=True):
        assert yaml_f.scale == py_f.scale, f"блок {name!r}, поле {yaml_f.name!r}: scale"
        assert yaml_f.signed == py_f.signed, f"блок {name!r}, поле {yaml_f.name!r}: signed"


# ─────────────────────── write_ops ──────────────────────────────────────────── #


def test_robot_write_ops_job_identical(robot_proto) -> None:
    """write_ops для CVT-задания идентичны у YAML и Python-карты."""
    values = {
        "job_x": 150.5,
        "job_y": -200.3,
        "job_flag": 1,
    }
    yaml_ops = robot_proto.register_map.write_ops(values)
    py_ops = _PY_MAP.write_ops(values)
    assert yaml_ops == py_ops


def test_robot_write_ops_draw_flag(robot_proto) -> None:
    """write_ops для draw_flag идентичны."""
    values = {"draw_type": 0, "draw_count": 5, "draw_flag": 1}
    yaml_ops = robot_proto.register_map.write_ops(values)
    py_ops = _PY_MAP.write_ops(values)
    assert yaml_ops == py_ops
