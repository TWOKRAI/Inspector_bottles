"""Parity-тест: YAML-протоколы ПЧ ↔ Python-карты.

Инвариант: YAML-файлы gd20_bridge.yaml и gd20_direct.yaml описывают ровно те
же карты регистров, что BRIDGE_MAP и DIRECT_MAP в core/registers.py.

Проверяется:
- Множество имён совпадает.
- Для каждой записи: тип, address, scale, signed, word_order.
- Для block-записей: имена полей, scale и signed каждого поля.
- write_ops с одинаковым dict дают идентичные ops у обеих карт.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from Services.modbus.core.protocol_file import load_protocol
from Services.modbus.core.register_map import Reg, RegBlock
from Services.vfd_comm.core.registers import BRIDGE_MAP, DIRECT_MAP

_PROTO_DIR = Path(__file__).resolve().parents[1] / "protocols"
_BRIDGE_PATH = _PROTO_DIR / "gd20_bridge.yaml"
_DIRECT_PATH = _PROTO_DIR / "gd20_direct.yaml"


# ─────────────────────── BRIDGE MAP ─────────────────────────────────────────── #


@pytest.fixture(scope="module")
def bridge_proto():
    """Загруженный YAML-протокол gd20_bridge."""
    return load_protocol(_BRIDGE_PATH)


def test_bridge_names_match(bridge_proto) -> None:
    """Множество имён записей YAML == Python-карта."""
    yaml_names = set(bridge_proto.register_map.names())
    py_names = set(BRIDGE_MAP.names())
    assert yaml_names == py_names, (
        f"Лишние в YAML: {yaml_names - py_names}, отсутствуют в YAML: {py_names - yaml_names}"
    )


def test_bridge_word_order(bridge_proto) -> None:
    """word_order в YAML совпадает с Python-картой."""
    assert bridge_proto.register_map.word_order == BRIDGE_MAP.word_order


@pytest.mark.parametrize(
    "name",
    ["cmd_run", "cmd_dir", "cmd_freq", "cmd_reset", "flag"],
)
def test_bridge_reg_address_scale_signed(bridge_proto, name: str) -> None:
    """Reg-записи: address/scale/signed совпадают."""
    yaml_entry = bridge_proto.register_map.entry(name)
    py_entry = BRIDGE_MAP.entry(name)
    assert isinstance(yaml_entry, Reg)
    assert isinstance(py_entry, Reg)
    assert yaml_entry.address == py_entry.address, f"{name}: address"
    assert yaml_entry.scale == py_entry.scale, f"{name}: scale"
    assert yaml_entry.signed == py_entry.signed, f"{name}: signed"


def test_bridge_block_address_count(bridge_proto) -> None:
    """status-блок: address и count совпадают."""
    yaml_entry = bridge_proto.register_map.entry("status")
    py_entry = BRIDGE_MAP.entry("status")
    assert isinstance(yaml_entry, RegBlock)
    assert isinstance(py_entry, RegBlock)
    assert yaml_entry.address == py_entry.address
    assert yaml_entry.count == py_entry.count


def test_bridge_block_field_names(bridge_proto) -> None:
    """status-блок: имена полей совпадают по порядку."""
    yaml_entry = bridge_proto.register_map.entry("status")
    py_entry = BRIDGE_MAP.entry("status")
    assert isinstance(yaml_entry, RegBlock)
    assert isinstance(py_entry, RegBlock)
    yaml_field_names = [f.name for f in yaml_entry.fields]
    py_field_names = [f.name for f in py_entry.fields]
    assert yaml_field_names == py_field_names


def test_bridge_block_field_scale_signed(bridge_proto) -> None:
    """status-блок: scale и signed каждого поля совпадают."""
    yaml_entry = bridge_proto.register_map.entry("status")
    py_entry = BRIDGE_MAP.entry("status")
    assert isinstance(yaml_entry, RegBlock)
    assert isinstance(py_entry, RegBlock)
    for yaml_f, py_f in zip(yaml_entry.fields, py_entry.fields, strict=True):
        assert yaml_f.scale == py_f.scale, f"поле {yaml_f.name}: scale"
        assert yaml_f.signed == py_f.signed, f"поле {yaml_f.name}: signed"


def test_bridge_write_ops_identical(bridge_proto) -> None:
    """write_ops({cmd_freq: 25.0, flag: 1}) у YAML и Python-карты идентичны."""
    values = {"cmd_freq": 25.0, "flag": 1}
    yaml_ops = bridge_proto.register_map.write_ops(values)
    py_ops = BRIDGE_MAP.write_ops(values)
    assert yaml_ops == py_ops


# ─────────────────────── DIRECT MAP ─────────────────────────────────────────── #


@pytest.fixture(scope="module")
def direct_proto():
    """Загруженный YAML-протокол gd20_direct."""
    return load_protocol(_DIRECT_PATH)


def test_direct_names_match(direct_proto) -> None:
    """Множество имён записей YAML == Python-карта DIRECT_MAP."""
    yaml_names = set(direct_proto.register_map.names())
    py_names = set(DIRECT_MAP.names())
    assert yaml_names == py_names, (
        f"Лишние в YAML: {yaml_names - py_names}, отсутствуют в YAML: {py_names - yaml_names}"
    )


def test_direct_word_order(direct_proto) -> None:
    """word_order в YAML совпадает с Python-картой."""
    assert direct_proto.register_map.word_order == DIRECT_MAP.word_order


@pytest.mark.parametrize(
    "name",
    ["cmd", "cmd_freq", "status_word"],
)
def test_direct_reg_address_scale_signed(direct_proto, name: str) -> None:
    """Reg-записи: address/scale/signed совпадают."""
    yaml_entry = direct_proto.register_map.entry(name)
    py_entry = DIRECT_MAP.entry(name)
    assert isinstance(yaml_entry, Reg)
    assert isinstance(py_entry, Reg)
    assert yaml_entry.address == py_entry.address, f"{name}: address"
    assert yaml_entry.scale == py_entry.scale, f"{name}: scale"
    assert yaml_entry.signed == py_entry.signed, f"{name}: signed"


def test_direct_block_monitor_address_count(direct_proto) -> None:
    """monitor-блок: address и count совпадают."""
    yaml_entry = direct_proto.register_map.entry("monitor")
    py_entry = DIRECT_MAP.entry("monitor")
    assert isinstance(yaml_entry, RegBlock)
    assert isinstance(py_entry, RegBlock)
    assert yaml_entry.address == py_entry.address
    assert yaml_entry.count == py_entry.count


def test_direct_block_monitor_field_names(direct_proto) -> None:
    """monitor-блок: имена полей совпадают по порядку."""
    yaml_entry = direct_proto.register_map.entry("monitor")
    py_entry = DIRECT_MAP.entry("monitor")
    assert isinstance(yaml_entry, RegBlock)
    assert isinstance(py_entry, RegBlock)
    yaml_field_names = [f.name for f in yaml_entry.fields]
    py_field_names = [f.name for f in py_entry.fields]
    assert yaml_field_names == py_field_names


def test_direct_block_monitor_field_scale_signed(direct_proto) -> None:
    """monitor-блок: scale и signed каждого поля совпадают."""
    yaml_entry = direct_proto.register_map.entry("monitor")
    py_entry = DIRECT_MAP.entry("monitor")
    assert isinstance(yaml_entry, RegBlock)
    assert isinstance(py_entry, RegBlock)
    for yaml_f, py_f in zip(yaml_entry.fields, py_entry.fields, strict=True):
        assert yaml_f.scale == py_f.scale, f"поле {yaml_f.name}: scale"
        assert yaml_f.signed == py_f.signed, f"поле {yaml_f.name}: signed"


def test_direct_write_ops_identical(direct_proto) -> None:
    """write_ops({cmd_freq: 30.0}) у YAML и Python-карты идентичны."""
    values = {"cmd_freq": 30.0}
    yaml_ops = direct_proto.register_map.write_ops(values)
    py_ops = DIRECT_MAP.write_ops(values)
    assert yaml_ops == py_ops
