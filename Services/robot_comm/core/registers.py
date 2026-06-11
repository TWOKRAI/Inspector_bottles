"""Карта регистров робота Delta — ЕДИНСТВЕННЫЙ источник истины протокола.

Пара к скрипту робота ``robot/universal3/cvt_universal_full.lua`` (режимы CVT
pick-place + рисование). Адреса/шкалы обязаны побайтово совпадать с Lua —
любое изменение протокола = парная правка Lua + этого модуля одним коммитом.

ВНИМАНИЕ: карта взята из universal3 (`pc_full.py`), НЕ из universal2 — версии
расходятся (CFG=11, TLM=11, DCBUS_SCALE=10, REG_MODE, drawing-блок).

Mailbox ПЧ (0x1200 команда / 0x1210 зеркало) физически живёт на роботе, но
принадлежит сервису ``Services/vfd_comm`` (SRP моста) — здесь его нет.
"""

from __future__ import annotations

from Services.modbus import Field, Reg, RegBlock, RegDW, RegisterMap

# ---------------------------------------------------------------------------- #
# Константы протокола (universal3)
# ---------------------------------------------------------------------------- #

ROBOT_UNIT_ID = 2  # Modbus device_id робота (ПЧ за мостом имеет свой id на RS-485)

MODE_CVT = 0
MODE_DRAW = 1

XY_SCALE = 10  # 0.1 мм на LSB
XY_LIMIT_MM = 3276.7  # предел s16 при scale=10

# Стоп-режимы (REG_STOP): семантика из Lua
STOP_HOME_CONTINUE = 1  # домой, остаться в цикле
STOP_HOME_EXIT = 2  # домой, выход, серво OFF
STOP_IN_PLACE = 3  # стоп на месте, выход, серво ON

SERVO_ON = 1
SERVO_OFF = 2

# Рисование: буфер точек и чанкование
REG_PTS_BASE = 0x1420
PTS_MAX = 100  # точек на один проход (батч) — дальше второй проход
WRITE_CHUNK = 30  # регистров за один write_registers (10 точек) — робот не тянет больше
REGS_PER_POINT = 3  # x, y, pen

DRAW_TYPE_POLYLINE = 0
DRAW_TYPE_CIRCLE = 1

# Адреса, нужные вне карты (sim, диагностика)
REG_MODE = 0x1109
REG_JOB_FLAG = 0x1100
REG_JOB_X = 0x1101
REG_JOB_Y = 0x1102
REG_JOB_ECAP = 0x1104
REG_STOP = 0x1106
REG_SERVO = 0x1108
REG_FREE = 0x1110
REG_ENC = 0x1112
REG_ECHO_BASE = 0x1120
REG_TLM_BASE = 0x1130
TLM_COUNT = 11
REG_CFG_FLAG = 0x1300
REG_CFG_BASE = 0x1301
CFG_COUNT = 11
REG_DRAW_FLAG = 0x1400
REG_DRAW_TYPE = 0x1401
REG_DRAW_COUNT = 0x1402
REG_DRAW_BUSY = 0x1403
REG_DRAW_PROG = 0x1404
REG_DRAW_ABORT = 0x1405

# Размер адресного пространства робота (для симулятора): drawing-буфер
# 0x1420 + 100 точек * 3 рег = 0x14A4, округляем с запасом.
REG_SPACE_SIZE = 0x1600

# Порядок полей конфиг-блока — индекс в блоке задаёт позицию (см. CFG_FIELDS Lua)
CONFIG_FIELDS: tuple[Field, ...] = (
    Field("speed"),
    Field("home_x", scale=XY_SCALE, signed=True),
    Field("home_y", scale=XY_SCALE, signed=True),
    Field("home_z", scale=XY_SCALE, signed=True),
    Field("pick_z", scale=XY_SCALE, signed=True),
    Field("place_x", scale=XY_SCALE, signed=True),
    Field("place_y", scale=XY_SCALE, signed=True),
    Field("place_z", scale=XY_SCALE, signed=True),
    Field("grip_ms"),
    Field("zone_max", scale=XY_SCALE, signed=True),
    Field("zone_min", scale=XY_SCALE, signed=True),
)

TELEMETRY_FIELDS: tuple[Field, ...] = (
    Field("x_mm", scale=XY_SCALE, signed=True),
    Field("y_mm", scale=XY_SCALE, signed=True),
    Field("z_mm", scale=XY_SCALE, signed=True),
    Field("rz_deg", scale=XY_SCALE, signed=True),
    Field("moving"),
    Field("spd_pct"),
    Field("belt_mm_s", signed=True),
    Field("hand"),
    Field("heartbeat"),
    Field("servo"),
    Field("miss_count"),
)

ECHO_FIELDS: tuple[Field, ...] = (
    Field("job_x", scale=XY_SCALE, signed=True),
    Field("job_y", scale=XY_SCALE, signed=True),
    Field("px", scale=XY_SCALE, signed=True),
    Field("py", scale=XY_SCALE, signed=True),
    Field("trav", scale=XY_SCALE, signed=True),
)


def build_register_map(word_order: str = "little") -> RegisterMap:
    """Собрать карту регистров робота.

    Args:
        word_order: порядок слов DW-полей (энкодер, E_capture). Из RobotConfig;
            подбирается на железе CLI-командой ``cal``.
    """
    rmap = RegisterMap(
        {
            "mode": Reg(REG_MODE),
            # --- CVT job (ПК -> робот) ---
            "job_flag": Reg(REG_JOB_FLAG),
            "job_x": Reg(REG_JOB_X, scale=XY_SCALE, signed=True),
            "job_y": Reg(REG_JOB_Y, scale=XY_SCALE, signed=True),
            "job_ecap": RegDW(REG_JOB_ECAP, signed=True),
            "stop": Reg(REG_STOP),
            "servo": Reg(REG_SERVO),
            # --- CVT статус (робот -> ПК) ---
            "free": Reg(REG_FREE),
            "encoder": RegDW(REG_ENC, signed=True),
            "echo": RegBlock(REG_ECHO_BASE, fields=ECHO_FIELDS),
            "telemetry": RegBlock(REG_TLM_BASE, fields=TELEMETRY_FIELDS),
            # --- конфиг робота ---
            "cfg_flag": Reg(REG_CFG_FLAG),
            "config": RegBlock(REG_CFG_BASE, fields=CONFIG_FIELDS),
            # --- рисование ---
            "draw_flag": Reg(REG_DRAW_FLAG),
            "draw_type": Reg(REG_DRAW_TYPE),
            "draw_count": Reg(REG_DRAW_COUNT),
            "draw_busy": Reg(REG_DRAW_BUSY),
            "draw_prog": Reg(REG_DRAW_PROG),
            "draw_abort": Reg(REG_DRAW_ABORT),
            "circ_cx": Reg(0x1406, scale=XY_SCALE, signed=True),
            "circ_cy": Reg(0x1407, scale=XY_SCALE, signed=True),
            "circ_r": Reg(0x1408, scale=XY_SCALE),
            "pen_down": Reg(0x1410, scale=XY_SCALE, signed=True),
            "pen_up": Reg(0x1411, scale=XY_SCALE, signed=True),
            "draw_spd": Reg(0x1412),
            "overlap": Reg(0x1413, scale=XY_SCALE),
        },
        word_order=word_order,  # type: ignore[arg-type]
    )
    _validate_dw_alignment(rmap)
    return rmap


def _validate_dw_alignment(rmap: RegisterMap) -> None:
    """DW-поля робота обязаны лежать по чётным адресам (требование Lua-стороны)."""
    for name in rmap.names():
        entry = rmap.entry(name)
        if isinstance(entry, RegDW) and entry.address % 2 != 0:
            raise ValueError(f"DW-регистр {name!r} (0x{entry.address:04X}) должен быть по чётному адресу")
