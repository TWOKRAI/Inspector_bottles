# СГЕНЕРИРОВАНО из Services/robot_comm/protocols/delta_v2.yaml (6f7b966e)
# не править руками; python -m Services.robot_comm.codegen

REG = {
    'CMD_FLAG': 0x1000,
    'CMD_SEQ': 0x1001,
    'CMD_OPCODE': 0x1002,
    'CMD_ARGC': 0x1003,
    'CMD_ARGS': 0x1004,
    'RES_SEQ': 0x1010,
    'RES_STATUS': 0x1011,
    'RES_ERRNO': 0x1012,
    'RES_RVALC': 0x1013,
    'RES_RVALS': 0x1014,
    'HB_PC': 0x1020,
    'STOP_REQ': 0x1021,
    'JOG_LEASE': 0x1022,
    'TLM_PROTO_VER': 0x1040,
    'TLM_FW_BUILD': 0x1041,
    'TLM_HB_ROBOT': 0x1042,
    'TLM_ACTIVITY': 0x1043,
    'TLM_X': 0x1044,
    'TLM_Y': 0x1045,
    'TLM_Z': 0x1046,
    'TLM_RZ': 0x1047,
    'TLM_MOVING': 0x1048,
    'TLM_SERVO': 0x1049,
    'TLM_SPD_PCT': 0x104A,
    'TLM_DO_MASK': 0x104B,
    'TLM_ENC': 0x104C,
    'TLM_BELT_MMS': 0x104E,
    'TLM_WDG_STATE': 0x104F,
    'TLM_ACK_SEQ': 0x1050,
    'TLM_DONE_SEQ': 0x1051,
    'TLM_ERR_SEQ': 0x1052,
    'TLM_ERRNO_LAST': 0x1053,
    'TLM_ERR_EVT': 0x1054,
    'TLM_ERR_COUNT': 0x1055,
    'TLM_SC_ID': 0x1056,
    'TLM_SC_TOTAL': 0x1057,
    'TLM_SC_INDEX': 0x1058,
    'TLM_SC_DONE_N': 0x1059,
    'TLM_MISS_COUNT': 0x105A,
    'TLM_HAND': 0x105B,
    'TLM_STOP_ACK': 0x105C,
    'TLM_CFG_EPOCH': 0x105D,
    'TLM_CFG_PENDING': 0x105E,
    'PMIR': 0x3000,
    'PMIR_MAGIC': 0x3080,
    'PMIR_CRC': 0x3081,
    'PMIR_DICT': 0x3082,
    'SC_BUF': 0x1400,
}

REG_COUNT = {
    'CMD_ARGS': 12,
    'RES_RVALS': 8,
    'PMIR': 128,
    'SC_BUF': 330,
}

OP = {
    'PING': 0x01,
    'CLEAR_ERR': 0x02,
    'PTP_MOVE': 0x10,
    'HOME': 0x11,
    'JOG_STEP': 0x12,
    'JOG_CONT': 0x13,
    'CVT_JOB': 0x20,
    'SC_RUN': 0x30,
    'SERVO': 0x41,
    'DO_SET': 0x42,
    'PARAM_SET': 0x50,
    'PARAM_GET': 0x51,
    'PARAM_APPLY': 0x52,
}

OP_SPEC = {
    'PING': {
        'argc': 0,
        'busy': 'allow',
        'args': [],
        'result': 'rvals',
    },
    'CLEAR_ERR': {
        'argc': 0,
        'busy': 'allow',
        'args': [],
        'result': 'instant',
    },
    'PTP_MOVE': {
        'argc': 6,
        'busy': 'deny',
        'args': [
            {
                'name': 'x',
                'type': 's16',
            },
            {
                'name': 'y',
                'type': 's16',
            },
            {
                'name': 'z',
                'type': 's16',
            },
            {
                'name': 'rz',
                'type': 's16',
            },
            {
                'name': 'kind',
                'type': 'u16',
            },
            {
                'name': 'spd_pct',
                'type': 'u16',
            },
        ],
        'result': 'done_seq',
    },
    'HOME': {
        'argc': 1,
        'busy': 'deny',
        'args': [
            {
                'name': 'spd_pct',
                'type': 'u16',
            },
        ],
        'result': 'done_seq',
    },
    'JOG_STEP': {
        'argc': 5,
        'busy': 'deny',
        'args': [
            {
                'name': 'dx',
                'type': 's16',
            },
            {
                'name': 'dy',
                'type': 's16',
            },
            {
                'name': 'dz',
                'type': 's16',
            },
            {
                'name': 'drz',
                'type': 's16',
            },
            {
                'name': 'spd_pct',
                'type': 'u16',
            },
        ],
        'result': 'done_seq',
    },
    'JOG_CONT': {
        'argc': 2,
        'busy': 'deny',
        'args': [
            {
                'name': 'direction',
                'type': 'u16',
            },
            {
                'name': 'speed',
                'type': 'u16',
            },
        ],
        'result': 'done_seq',
    },
    'CVT_JOB': {
        'argc': 10,
        'busy': 'deny',
        'args': [
            {
                'name': 'ecap_lo',
                'type': 'dw_lo',
            },
            {
                'name': 'ecap_hi',
                'type': 'dw_hi',
            },
            {
                'name': 'pick_x',
                'type': 's16',
            },
            {
                'name': 'pick_y',
                'type': 's16',
            },
            {
                'name': 'pick_z',
                'type': 's16',
            },
            {
                'name': 'flags',
                'type': 'u16',
            },
            {
                'name': 'place_x',
                'type': 's16',
            },
            {
                'name': 'place_y',
                'type': 's16',
            },
            {
                'name': 'place_z',
                'type': 's16',
            },
            {
                'name': 'place_rz',
                'type': 's16',
            },
        ],
        'result': 'done_seq',
    },
    'SC_RUN': {
        'argc': 3,
        'busy': 'deny',
        'args': [
            {
                'name': 'count',
                'type': 'u16',
            },
            {
                'name': 'sc_id',
                'type': 'u16',
            },
            {
                'name': 'offset',
                'type': 'u16',
            },
        ],
        'result': 'done_seq',
    },
    'SERVO': {
        'argc': 1,
        'busy': 'deny',
        'args': [
            {
                'name': 'on',
                'type': 'u16',
            },
        ],
        'result': 'instant',
    },
    'DO_SET': {
        'argc': 2,
        'busy': 'deny',
        'args': [
            {
                'name': 'channel',
                'type': 'u16',
            },
            {
                'name': 'value',
                'type': 'u16',
            },
        ],
        'result': 'instant',
    },
    'PARAM_SET': {
        'argc': 2,
        'busy': 'by_class',
        'args': [
            {
                'name': 'id',
                'type': 'u16',
            },
            {
                'name': 'value',
                'type': 'raw',
            },
        ],
        'result': 'instant',
    },
    'PARAM_GET': {
        'argc': 1,
        'busy': 'allow',
        'args': [
            {
                'name': 'id',
                'type': 'u16',
            },
        ],
        'result': 'rvals',
    },
    'PARAM_APPLY': {
        'argc': 0,
        'busy': 'deny',
        'args': [],
        'result': 'instant',
    },
}

ERR = {
    'E_OK': 0,
    'E_BAD_OPCODE': 1,
    'E_BAD_ARGC': 2,
    'E_RANGE': 3,
    'E_BUSY': 4,
    'E_BAD_PARAM': 5,
    'E_NO_SERVO': 6,
    'E_SC_COUNT': 7,
    'E_SC_RECORD': 8,
    'E_BUF_SHORT': 9,
    'E_WDG_TIMEOUT': 10,
    'E_MOTION_FAULT': 11,
    'E_ZONE_TRIP': 12,
    'E_ABORTED': 13,
    'E_INTERNAL': 14,
    'E_CFG_PENDING': 15,
    'E_VFD_LINK': 16,
}

ERR_TEXT = {
    0: 'ОК',
    1: 'Неизвестная команда',
    2: 'Неверное число аргументов',
    3: 'Значение или цель вне допустимого диапазона (rval0 — причина)',
    4: 'Робот занят другой командой',
    5: 'Неизвестный параметр',
    6: 'Серво выключено — движение невозможно',
    7: 'Недопустимое число точек или смещение в буфере',
    8: 'Ошибка в точке сценария (rval0 — индекс, rval1 — причина)',
    9: 'Буфер сценария прочитан не полностью',
    10: 'Пропала связь с ПК — лента и движение остановлены',
    11: 'Контроллер движения в ошибке',
    12: 'Объект вышел из рабочей зоны ленты',
    13: 'Движение прервано стопом',
    14: 'Внутренняя ошибка прошивки',
    15: 'Параметры приняты, но не применены — выполните «Применить»',
    16: 'ПЧ не отвечает по RS-485',
}

ERR_KIND = {
    0: 'none',
    1: 'sync',
    2: 'sync',
    3: 'sync',
    4: 'sync',
    5: 'sync',
    6: 'sync',
    7: 'sync',
    8: 'sync',
    9: 'sync',
    10: 'async',
    11: 'async',
    12: 'async',
    13: 'async',
    14: 'both',
    15: 'sync',
    16: 'async',
}

REASON = {
    'R_KIND': 1,
    'R_ACTION': 2,
    'R_APARAM': 3,
    'R_OUT_OF_ZONE': 4,
    'R_DEAD_ZONE': 5,
    'R_LAST_PASS': 6,
    'R_HAND': 7,
    'R_JOG_TOO_LONG': 8,
}

REASON_TEXT = {
    1: 'KIND',
    2: 'ACTION',
    3: 'APARAM',
    4: 'точка вне зоны',
    5: 'отрезок LINE проходит через мёртвую зону у оси J1',
    6: 'последняя точка LINE_PASS',
    7: 'чужая конфигурация руки',
    8: 'JOG длиннее P_JOG_MAX',
}

CONSTANTS = {
    'PROTO_VER': 0x0200,
    'CMD_BASE': 0x1000,
    'RES_BASE': 0x1010,
    'SAFETY_BASE': 0x1020,
    'TLM_BASE': 0x1040,
    'SC_BASE': 0x1400,
    'PMIR_BASE': 0x3000,
    'PMIR_FALLBACK_BASE': 0x1300,
    'VFD_BASE': 0x1200,
    'SC_STRIDE': 6,
    'SC_CAP': 55,
    'WRITE_CHUNK': 30,
    'READ_MAX': 125,
    'W_MIN': -32767,
    'W_MAX': 32767,
    'PMIR_MAGIC_VALUE': 0x5632,
}

GATE1_CONSTANTS = (
    'PMIR_BASE',
    'SC_CAP',
)

KIND = {
    'LINE': 0,
    'LINE_PASS': 1,
    'JOINT': 2,
}

ACT = {
    'NONE': 0,
    'DO_ON': 1,
    'DO_OFF': 2,
    'DELAY_MS': 3,
    'SPEED_PCT': 4,
    'ACCEL': 5,
    'ACCUR': 6,
}

STOP_LEVEL = {
    'SOFT': 1,
    'HARD': 2,
    'HALT': 3,
}

SC_RECORD = (
    'x',
    'y',
    'z',
    'rz',
    'op',
    'aparam',
)
