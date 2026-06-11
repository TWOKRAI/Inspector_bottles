"""Карты регистров ПЧ INVT GD20 — единственный источник истины протокола.

Две карты на один физический ПЧ — по способу подключения:

1. **BRIDGE (мост через робота, текущий путь):** ПК пишет mailbox-регистры
   робота (0x1200 команда), Lua ретранслирует на RS-485 и зеркалит статус
   (0x1210). Транспорт — `RobotClient` (RegisterTransport).
2. **DIRECT (прямое RTU-подключение, закладка):** регистры самого GD20 по
   мануалу goodrive20 (0x2000 команда, 0x2100 статус, 0x3000 мониторинг).
   Транспорт — `ModbusDevice(transport=rtu)`. Полей heartbeat/comm_err НЕТ —
   они существуют только в мосте.

Mailbox-адреса обязаны совпадать с `cvt_universal_full.lua`; прямые — с
P14-группой настроек GD20 (slave id ПЧ задаёт P14.00, по умолчанию 1 —
это забота Lua/конфига RTU, клиент ПЧ slave id не знает).
"""

from __future__ import annotations

from Services.modbus import Field, Reg, RegBlock, RegisterMap

FREQ_SCALE = 100  # 0.01 Гц на LSB (общая конвенция GD20 и моста)
CURRENT_SCALE = 10  # 0.1 А
DCBUS_SCALE = 10  # 0.1 В (universal3; в u2 было 1!)

# Состояния STATUSW зеркала (из Lua: 1=FWD, 2=REV, 3=STOP, 4=FAULT)
STATE_FWD = 1
STATE_REV = 2
STATE_STOP = 3
STATE_FAULT = 4

# --- BRIDGE: mailbox на роботе (сторона ПК) ---
REG_CMD_RUN = 0x1200
REG_CMD_DIR = 0x1201
REG_CMD_FREQ = 0x1202
REG_CMD_RESET = 0x1203
REG_VFD_FLAG = 0x1204
REG_ST_BASE = 0x1210
ST_COUNT = 8

_BRIDGE_STATUS_FIELDS: tuple[Field, ...] = (
    Field("running"),
    Field("out_freq_hz", scale=FREQ_SCALE),
    Field("current_a", scale=CURRENT_SCALE),
    Field("dcbus_v", scale=DCBUS_SCALE),
    Field("fault"),
    Field("status_word"),
    Field("heartbeat"),
    Field("comm_errors"),
)

BRIDGE_MAP = RegisterMap(
    {
        "cmd_run": Reg(REG_CMD_RUN),
        "cmd_dir": Reg(REG_CMD_DIR),
        "cmd_freq": Reg(REG_CMD_FREQ, scale=FREQ_SCALE),
        "cmd_reset": Reg(REG_CMD_RESET),
        "flag": Reg(REG_VFD_FLAG),
        "status": RegBlock(REG_ST_BASE, fields=_BRIDGE_STATUS_FIELDS),
    }
)

# --- DIRECT: регистры GD20 (закладка под будущее прямое RTU) ---
# Источник: мануал goodrive20-series-inverter (группа communication registers).
GD20_REG_CMD = 0x2000  # 1=RUN FWD, 2=RUN REV, 5=STOP, 7=FAULT RESET
GD20_REG_FREQ = 0x2001  # уставка, x100
GD20_REG_STATUS = 0x2100  # 1=FWD, 2=REV, 3=STOP, 4=FAULT
GD20_REG_MON = 0x3000  # блок мониторинга: уставка, out_freq, dcbus, ..., current

GD20_CMD_RUN_FWD = 1
GD20_CMD_RUN_REV = 2
GD20_CMD_STOP = 5
GD20_CMD_FAULT_RESET = 7

DIRECT_MAP = RegisterMap(
    {
        "cmd": Reg(GD20_REG_CMD),
        "cmd_freq": Reg(GD20_REG_FREQ, scale=FREQ_SCALE),
        "status_word": Reg(GD20_REG_STATUS),
        "monitor": RegBlock(
            GD20_REG_MON,
            fields=(
                Field("set_freq_hz", scale=FREQ_SCALE),
                Field("out_freq_hz", scale=FREQ_SCALE),
                Field("dcbus_v", scale=DCBUS_SCALE),
                Field("out_voltage_v"),
                Field("current_a", scale=CURRENT_SCALE),
            ),
        ),
    }
)
