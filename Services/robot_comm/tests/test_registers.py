"""Тесты карты регистров робота — без сети, без pymodbus."""

from __future__ import annotations

import pytest

from Services.modbus import Reg, RegBlock, RegDW

from Services.robot_comm.core.config import RobotConfig
from Services.robot_comm.core.registers import (
    CFG_COUNT,
    CONFIG_FIELDS,
    REG_CFG_BASE,
    REG_ECHO_BASE,
    REG_ENC,
    REG_JOB_ECAP,
    REG_TLM_BASE,
    TLM_COUNT,
    XY_SCALE,
    build_register_map,
)


def test_map_builds_with_both_word_orders() -> None:
    for order in ("big", "little"):
        rmap = build_register_map(order)
        assert rmap.word_order == order


def test_job_registers_addresses_and_scales() -> None:
    """Контракт с Lua: адреса/шкалы job-блока (universal3)."""
    rmap = build_register_map()
    flag = rmap.entry("job_flag")
    x = rmap.entry("job_x")
    ecap = rmap.entry("job_ecap")
    assert isinstance(flag, Reg) and flag.address == 0x1100
    assert isinstance(x, Reg) and x.address == 0x1101 and x.scale == XY_SCALE and x.signed
    assert isinstance(ecap, RegDW) and ecap.address == REG_JOB_ECAP and ecap.signed


def test_telemetry_block_eleven_words() -> None:
    """u3-телеметрия — 11 слов (НЕ 10 как в u2)."""
    rmap = build_register_map()
    tlm = rmap.entry("telemetry")
    assert isinstance(tlm, RegBlock)
    assert tlm.address == REG_TLM_BASE
    assert tlm.count == TLM_COUNT == 11
    names = [f.name for f in tlm.fields]
    assert names[:4] == ["x_mm", "y_mm", "z_mm", "rz_deg"]
    assert "belt_mm_s" in names and "miss_count" in names


def test_config_block_eleven_fields_u3() -> None:
    """u3-конфиг — 11 полей, включая place_* и pick_z (нет в u2)."""
    rmap = build_register_map()
    cfg = rmap.entry("config")
    assert isinstance(cfg, RegBlock)
    assert cfg.address == REG_CFG_BASE
    assert cfg.count == CFG_COUNT == len(CONFIG_FIELDS) == 11
    names = [f.name for f in cfg.fields]
    assert names == [
        "speed",
        "home_x",
        "home_y",
        "home_z",
        "pick_z",
        "place_x",
        "place_y",
        "place_z",
        "grip_ms",
        "zone_max",
        "zone_min",
    ]


def test_echo_block_five_signed_scaled() -> None:
    rmap = build_register_map()
    echo = rmap.entry("echo")
    assert isinstance(echo, RegBlock) and echo.address == REG_ECHO_BASE and echo.count == 5
    assert all(f.scale == XY_SCALE and f.signed for f in echo.fields)


def test_dw_registers_even_aligned() -> None:
    """DW-поля робота обязаны лежать по чётным адресам (требование Lua)."""
    rmap = build_register_map()
    for name in ("encoder", "job_ecap"):
        entry = rmap.entry(name)
        assert isinstance(entry, RegDW)
        assert entry.address % 2 == 0
    assert REG_ENC % 2 == 0


def test_drawing_registers_present() -> None:
    rmap = build_register_map()
    for name in ("draw_flag", "draw_type", "draw_count", "draw_busy", "draw_prog", "draw_abort"):
        assert name in rmap
    pen = rmap.entry("pen_down")
    assert isinstance(pen, Reg) and pen.scale == XY_SCALE and pen.signed


def test_robot_config_roundtrip_and_modbus() -> None:
    cfg = RobotConfig(host="10.0.0.5", word_order="big")
    restored = RobotConfig.from_dict(cfg.to_dict() | {"мусор": 1})
    assert restored == cfg
    mb = cfg.to_modbus_config()
    assert mb.host == "10.0.0.5" and mb.unit_id == 2 and mb.word_order == "big"
    assert mb.timeout_sec == pytest.approx(1.0)  # малый таймаут: Lock на время I/O
