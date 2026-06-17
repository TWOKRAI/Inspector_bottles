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
MODE_MANUAL = 2  # ручной jog по Modbus (dX/dY + скорость)
MODE_RETURN = 3  # возврат выложенной буквы на ленту (статичный забор из слота + линейная траектория)
MODE_TOOLCHANGE = 4  # смена инструмента (возврат текущего в гнездо + надевание целевого)

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
REG_JOB_Z = 0x1103  # глубина захвата на picke, 0.1 мм (свободный слот между job_y и job_ecap); 0 = Z_PICK
REG_JOB_ECAP = 0x1104
# --- CVT: поза УКЛАДКИ x/y/z/r (доворот) — свободный блок 0x1140 ---
# Забор остаётся по job_x/job_y (трекинг ленты). При place_flag=1 робот кладёт в
# place_x/y/z под АБСОЛЮТНЫМ R = place_rz (драйвер опрашивает реальный R инструмента
# по телеметрии и шлёт place_rz = реальный R + доворот). place_flag=0 → фикс. GL_PLACE.
REG_PLACE_X = 0x1140
REG_PLACE_Y = 0x1141
REG_PLACE_Z = 0x1142
REG_PLACE_RZ = 0x1143
REG_PLACE_FLAG = 0x1144
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
# Эхо факта выполнения прохода (read-back ACK): прошивка пишет сюда РЕАЛЬНО выполненное
# число точек (пост-усечённое, см. execute_path: при коротком чтении буфера count
# уменьшается молча). Клиент сверяет с размером пачки → ловит потерю, повторяет/абортит.
# В отличие от draw_prog (0x1404), НЕ обнуляется в конце прохода — иначе нечего читать.
REG_DRAW_DONE_N = 0x1409
# 1 = после прохода ехать домой (последний проход рисунка); 0 = ждать на месте
REG_DRAW_HOME = 0x1414

# ⚠️ Командные блоки режимов — в свободной дыре 0x1340..0x13FF (между CONFIG 0x130B и
# DRAW 0x1400), НИЖЕ буфера точек рисования 0x1420..0x154B. Раньше стояли на 0x1500/0x1510 —
# ВНУТРИ буфера: рисунок ≥76 точек затирал эти регистры (режимы конфликтовали по адресам).
# Блоки выровнены по 0x10 (16 рег на слот) — запас под рост каждого режима.
# MANUAL: ручной jog по Modbus (0x1340..0x1346)
REG_MAN_FLAG = 0x1340
REG_MAN_DX = 0x1341
REG_MAN_DY = 0x1342
REG_MAN_SPD = 0x1343
REG_MAN_BUSY = 0x1344
REG_MAN_ABORT = 0x1345
REG_MAN_ABS = 0x1346

# RETURN: возврат выложенной буквы на ленту (0x1350..0x1354). MODE=3.
# ПК пишет координату СЛОТА (x,y,z — откуда забрать) + ret_flag=1 (маркер последним).
# Робот в MODE=3: подвод к слоту → захват (DO в Lua) → линейно +RET_LIFT по Z → +RET_PUSH
# по X → −RET_LIFT по Z → отпустить → домой. Смещения (подъём/сдвиг) — КОНСТАНТЫ Lua.
# Handshake как у рисования: ret_flag 1→0 (приём) → ret_busy 1 (старт) → ret_busy 0 (готово).
REG_RET_FLAG = 0x1350
REG_RET_X = 0x1351
REG_RET_Y = 0x1352
REG_RET_Z = 0x1353
REG_RET_BUSY = 0x1354

# TOOLCHANGE: смена инструмента (0x1360..0x1363). MODE=4.
# ПК пишет REG_TOOL_TARGET (0=снять/1/2) + REG_TOOL_FLAG=1 (маркер последним).
# Робот в MODE=4: едет в гнездо текущего инструмента → снимает → едет в гнездо
# целевого → надевает → домой. Handshake: tool_flag 1→0 (приём) → tool_busy
# 1 (старт) → tool_busy 0 (готово). REG_TOOL_CUR — текущий инструмент (зеркало).
REG_TOOL_FLAG = 0x1360
REG_TOOL_TARGET = 0x1361
REG_TOOL_BUSY = 0x1362
REG_TOOL_CUR = 0x1363

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
            "job_z": Reg(REG_JOB_Z, scale=XY_SCALE, signed=True),
            "job_ecap": RegDW(REG_JOB_ECAP, signed=True),
            # --- CVT поза укладки x/y/z/r (доворот); place_flag — маркер режима укладки ---
            "place_x": Reg(REG_PLACE_X, scale=XY_SCALE, signed=True),
            "place_y": Reg(REG_PLACE_Y, scale=XY_SCALE, signed=True),
            "place_z": Reg(REG_PLACE_Z, scale=XY_SCALE, signed=True),
            "place_rz": Reg(REG_PLACE_RZ, scale=XY_SCALE, signed=True),
            "place_flag": Reg(REG_PLACE_FLAG),
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
            "draw_done_n": Reg(REG_DRAW_DONE_N),  # read-back ACK: реально выполнено точек
            "circ_cx": Reg(0x1406, scale=XY_SCALE, signed=True),
            "circ_cy": Reg(0x1407, scale=XY_SCALE, signed=True),
            "circ_r": Reg(0x1408, scale=XY_SCALE),
            "pen_down": Reg(0x1410, scale=XY_SCALE, signed=True),
            "pen_up": Reg(0x1411, scale=XY_SCALE, signed=True),
            "draw_spd": Reg(0x1412),
            "overlap": Reg(0x1413, scale=XY_SCALE),
            "draw_home": Reg(REG_DRAW_HOME),
            # --- MANUAL: ручной jog ---
            "man_flag": Reg(REG_MAN_FLAG),
            "man_dx": Reg(REG_MAN_DX, scale=XY_SCALE, signed=True),
            "man_dy": Reg(REG_MAN_DY, scale=XY_SCALE, signed=True),
            "man_spd": Reg(REG_MAN_SPD),
            "man_busy": Reg(REG_MAN_BUSY),
            "man_abort": Reg(REG_MAN_ABORT),
            "man_abs": Reg(REG_MAN_ABS),
            # --- RETURN: возврат буквы на ленту (координата слота + handshake) ---
            "ret_flag": Reg(REG_RET_FLAG),
            "ret_x": Reg(REG_RET_X, scale=XY_SCALE, signed=True),
            "ret_y": Reg(REG_RET_Y, scale=XY_SCALE, signed=True),
            "ret_z": Reg(REG_RET_Z, scale=XY_SCALE, signed=True),
            "ret_busy": Reg(REG_RET_BUSY),
            # --- TOOLCHANGE: смена инструмента (target + handshake) ---
            "tool_flag": Reg(REG_TOOL_FLAG),
            "tool_target": Reg(REG_TOOL_TARGET),
            "tool_busy": Reg(REG_TOOL_BUSY),
            "tool_cur": Reg(REG_TOOL_CUR),
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
