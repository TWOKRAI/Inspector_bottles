"""Тесты загрузчика YAML-протоколов устройств.

Проверяется: загрузка минимального протокола, все типы записей (reg/dw/block),
метаданные RegisterMeta (label/unit/min/max/access/default), word_order,
валидация ошибок, find_protocols, to_dict.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from Services.modbus.core.protocol_file import (
    DeviceProtocol,
    ProtocolFileError,
    RegisterMeta,
    find_protocols,
    load_protocol,
)
from Services.modbus.core.register_map import Reg, RegBlock, RegDW, RegisterMap


# ─────────────────────── хелперы ────────────────────────────────────────────── #


def _write_yaml(tmp_path: Path, data: dict, name: str = "proto.yaml") -> Path:
    """Записать dict как YAML-файл и вернуть путь."""
    p = tmp_path / name
    p.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    return p


def _minimal_yaml(tmp_path: Path, extra_registers: dict | None = None) -> Path:
    """Минимально валидный протокол с одним reg-регистром."""
    data = {
        "name": "test_proto",
        "kind": "test",
        "registers": {
            "flag": {"type": "reg", "address": 0x1100},
            **(extra_registers or {}),
        },
    }
    return _write_yaml(tmp_path, data)


# ─────────────────────── загрузка базового протокола ────────────────────────── #


def test_load_minimal_protocol(tmp_path: Path) -> None:
    """Минимальный протокол: name/kind/registers — загружается без ошибок."""
    path = _minimal_yaml(tmp_path)
    proto = load_protocol(path)
    assert isinstance(proto, DeviceProtocol)
    assert proto.name == "test_proto"
    assert proto.kind == "test"
    assert proto.description == ""
    assert isinstance(proto.register_map, RegisterMap)
    assert "flag" in proto.register_map


def test_load_protocol_description(tmp_path: Path) -> None:
    """description — опциональное поле, попадает в DeviceProtocol."""
    data = {
        "name": "p",
        "kind": "vfd",
        "description": "Тестовое описание",
        "registers": {"r": {"type": "reg", "address": 0x100}},
    }
    proto = load_protocol(_write_yaml(tmp_path, data))
    assert proto.description == "Тестовое описание"


# ─────────────────────── типы записей ───────────────────────────────────────── #


def test_load_reg_entry(tmp_path: Path) -> None:
    """Тип reg: address, scale, signed попадают в Reg."""
    data = {
        "name": "p",
        "kind": "test",
        "registers": {"freq": {"type": "reg", "address": 0x1202, "scale": 100, "signed": False}},
    }
    proto = load_protocol(_write_yaml(tmp_path, data))
    entry = proto.register_map.entry("freq")
    assert isinstance(entry, Reg)
    assert entry.address == 0x1202
    assert entry.scale == 100.0
    assert entry.signed is False


def test_load_dw_entry(tmp_path: Path) -> None:
    """Тип dw: address, signed попадают в RegDW."""
    data = {
        "name": "p",
        "kind": "test",
        "registers": {"encoder": {"type": "dw", "address": 0x1112, "signed": True}},
    }
    proto = load_protocol(_write_yaml(tmp_path, data))
    entry = proto.register_map.entry("encoder")
    assert isinstance(entry, RegDW)
    assert entry.address == 0x1112
    assert entry.signed is True


def test_load_block_entry_with_fields(tmp_path: Path) -> None:
    """Тип block с fields: RegBlock создаётся с именованными полями."""
    data = {
        "name": "p",
        "kind": "test",
        "registers": {
            "status": {
                "type": "block",
                "address": 0x1210,
                "fields": [
                    {"name": "running"},
                    {"name": "out_freq_hz", "scale": 100},
                ],
            }
        },
    }
    proto = load_protocol(_write_yaml(tmp_path, data))
    entry = proto.register_map.entry("status")
    assert isinstance(entry, RegBlock)
    assert entry.address == 0x1210
    assert entry.count == 2
    assert entry.fields[0].name == "running"
    assert entry.fields[1].scale == 100.0


def test_load_block_entry_count_only(tmp_path: Path) -> None:
    """Тип block с count (без fields): RegBlock(count=N) без имён полей."""
    data = {
        "name": "p",
        "kind": "test",
        "registers": {"raw_buf": {"type": "block", "address": 0x2000, "count": 5}},
    }
    proto = load_protocol(_write_yaml(tmp_path, data))
    entry = proto.register_map.entry("raw_buf")
    assert isinstance(entry, RegBlock)
    assert entry.count == 5
    assert entry.fields == ()


# ─────────────────────── метаданные RegisterMeta ────────────────────────────── #


def test_meta_label_unit_min_max_access_default(tmp_path: Path) -> None:
    """Метаданные label/unit/min/max/access/default попадают в RegisterMeta."""
    data = {
        "name": "p",
        "kind": "vfd",
        "registers": {
            "cmd_freq": {
                "type": "reg",
                "address": 0x1202,
                "scale": 100,
                "access": "w",
                "label": "Частота",
                "unit": "Гц",
                "hint": "Уставка",
                "min": 0,
                "max": 50,
                "default": 10,
            }
        },
    }
    proto = load_protocol(_write_yaml(tmp_path, data))
    meta = proto.meta["cmd_freq"]
    assert isinstance(meta, RegisterMeta)
    assert meta.label == "Частота"
    assert meta.unit == "Гц"
    assert meta.hint == "Уставка"
    assert meta.access == "w"
    assert meta.min == 0.0
    assert meta.max == 50.0
    assert meta.default == 10.0


def test_meta_access_default_is_r(tmp_path: Path) -> None:
    """Если access не задан — значение по умолчанию 'r'."""
    proto = load_protocol(_minimal_yaml(tmp_path))
    assert proto.meta["flag"].access == "r"


# ─────────────────────── word_order ──────────────────────────────────────────── #


def test_word_order_little(tmp_path: Path) -> None:
    """word_order: little передаётся в RegisterMap."""
    data = {
        "name": "p",
        "kind": "robot",
        "word_order": "little",
        "registers": {"enc": {"type": "dw", "address": 0x1112, "signed": True}},
    }
    proto = load_protocol(_write_yaml(tmp_path, data))
    assert proto.register_map.word_order == "little"


def test_word_order_default_is_big(tmp_path: Path) -> None:
    """word_order по умолчанию — big."""
    proto = load_protocol(_minimal_yaml(tmp_path))
    assert proto.register_map.word_order == "big"


# ─────────────────────── ошибки валидации ────────────────────────────────────── #


def test_error_duplicate_address(tmp_path: Path) -> None:
    """Два регистра с одинаковым адресом → ProtocolFileError."""
    data = {
        "name": "p",
        "kind": "test",
        "registers": {
            "a": {"type": "reg", "address": 0x1200},
            "b": {"type": "reg", "address": 0x1200},
        },
    }
    with pytest.raises(ProtocolFileError, match="перекрытие адресов"):
        load_protocol(_write_yaml(tmp_path, data))


def test_error_dw_overlaps_next_reg(tmp_path: Path) -> None:
    """DW занимает 2 слова — перекрывает соседний регистр → ProtocolFileError."""
    data = {
        "name": "p",
        "kind": "test",
        "registers": {
            "enc": {"type": "dw", "address": 0x1112},  # 0x1112..0x1113
            "next_reg": {"type": "reg", "address": 0x1113},  # перекрытие!
        },
    }
    with pytest.raises(ProtocolFileError, match="перекрытие адресов"):
        load_protocol(_write_yaml(tmp_path, data))


def test_error_bad_access(tmp_path: Path) -> None:
    """access не из {r, w, rw} → ProtocolFileError."""
    data = {
        "name": "p",
        "kind": "test",
        "registers": {"x": {"type": "reg", "address": 0x100, "access": "read"}},
    }
    with pytest.raises(ProtocolFileError, match="access"):
        load_protocol(_write_yaml(tmp_path, data))


def test_error_scale_zero(tmp_path: Path) -> None:
    """scale = 0 → ProtocolFileError."""
    data = {
        "name": "p",
        "kind": "test",
        "registers": {"x": {"type": "reg", "address": 0x100, "scale": 0}},
    }
    with pytest.raises(ProtocolFileError, match="scale"):
        load_protocol(_write_yaml(tmp_path, data))


def test_error_scale_negative(tmp_path: Path) -> None:
    """scale < 0 → ProtocolFileError."""
    data = {
        "name": "p",
        "kind": "test",
        "registers": {"x": {"type": "reg", "address": 0x100, "scale": -1}},
    }
    with pytest.raises(ProtocolFileError, match="scale"):
        load_protocol(_write_yaml(tmp_path, data))


def test_error_unknown_type(tmp_path: Path) -> None:
    """Неизвестный type → ProtocolFileError."""
    data = {
        "name": "p",
        "kind": "test",
        "registers": {"x": {"type": "qword", "address": 0x100}},
    }
    with pytest.raises(ProtocolFileError, match="неизвестный type"):
        load_protocol(_write_yaml(tmp_path, data))


def test_error_block_without_fields_and_count(tmp_path: Path) -> None:
    """block без fields и без count → ProtocolFileError."""
    data = {
        "name": "p",
        "kind": "test",
        "registers": {"blk": {"type": "block", "address": 0x1210}},
    }
    with pytest.raises(ProtocolFileError, match="'fields' или 'count'"):
        load_protocol(_write_yaml(tmp_path, data))


def test_error_bad_word_order(tmp_path: Path) -> None:
    """word_order = 'middle' → ProtocolFileError."""
    data = {
        "name": "p",
        "kind": "test",
        "word_order": "middle",
        "registers": {"x": {"type": "reg", "address": 0x100}},
    }
    with pytest.raises(ProtocolFileError, match="word_order"):
        load_protocol(_write_yaml(tmp_path, data))


# ─────────────────────── find_protocols ────────────────────────────────────────


def test_find_protocols_finds_three_real_files() -> None:
    """find_protocols() без фильтра находит минимум 3 реальных файла."""
    result = find_protocols()
    assert len(result) >= 3
    # Все значения — файлы
    for name, path in result.items():
        assert path.is_file(), f"{name}: файл не существует: {path}"
        assert path.suffix == ".yaml"


def test_find_protocols_kind_vfd_filter() -> None:
    """find_protocols(kind='vfd') возвращает только vfd-протоколы."""
    result = find_protocols(kind="vfd")
    assert len(result) >= 1
    for name in result:
        assert "gd20" in name, f"ожидается gd20-файл, получено {name!r}"


def test_find_protocols_kind_robot_filter() -> None:
    """find_protocols(kind='robot') возвращает протоколы роботов."""
    result = find_protocols(kind="robot")
    assert len(result) >= 1


def test_find_protocols_nonexistent_kind_returns_empty() -> None:
    """find_protocols(kind='nonexistent') возвращает пустой dict."""
    result = find_protocols(kind="nonexistent_kind_xyz")
    assert result == {}


# ─────────────────────── to_dict ─────────────────────────────────────────────── #


def test_register_meta_to_dict_basic(tmp_path: Path) -> None:
    """to_dict() возвращает корректный dict без поля 'fields' для reg."""
    data = {
        "name": "p",
        "kind": "vfd",
        "registers": {
            "cmd_freq": {
                "type": "reg",
                "address": 0x1202,
                "scale": 100,
                "access": "w",
                "label": "Частота",
                "unit": "Гц",
                "min": 0,
                "max": 50,
            }
        },
    }
    proto = load_protocol(_write_yaml(tmp_path, data))
    d = proto.meta["cmd_freq"].to_dict()
    assert d["name"] == "cmd_freq"
    assert d["kind"] == "reg"
    assert d["label"] == "Частота"
    assert d["unit"] == "Гц"
    assert d["access"] == "w"
    assert d["scale"] == 100.0
    assert d["min"] == 0.0
    assert d["max"] == 50.0
    assert "fields" not in d  # у reg нет вложенных полей


def test_register_meta_to_dict_block_recursive(tmp_path: Path) -> None:
    """to_dict() рекурсивно сериализует fields блока."""
    data = {
        "name": "p",
        "kind": "test",
        "registers": {
            "status": {
                "type": "block",
                "address": 0x1210,
                "fields": [
                    {"name": "running", "label": "Вращение"},
                    {"name": "freq", "scale": 100, "unit": "Гц"},
                ],
            }
        },
    }
    proto = load_protocol(_write_yaml(tmp_path, data))
    d = proto.meta["status"].to_dict()
    assert "fields" in d
    assert len(d["fields"]) == 2
    assert d["fields"][0]["name"] == "running"
    assert d["fields"][1]["unit"] == "Гц"
