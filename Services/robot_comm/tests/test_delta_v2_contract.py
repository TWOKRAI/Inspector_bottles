"""RED-приёмка контракта `Services/robot_comm/protocols/delta_v2.yaml` (T0.1).

Источник истины — protocol-spec.md (§3/§5/§6/§7.1/§8) и params.md (§11.3), НЕ сам
YAML: каждое ожидаемое значение здесь — литерал, переписанный из документа руками,
а не производное от загруженного файла. Файл `delta_v2.yaml` ещё не существует —
все тесты обязаны падать на `FileNotFoundError` внутри фикстур `raw_yaml`/`proto`
(коллекция модуля при этом проходит успешно, ошибок импорта нет).

Независимый тестировщик, слепой к реализации: писался ДО `delta_v2.yaml`, без
доступа к `delta_v2*`/`*_v2.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from Services.modbus.core.protocol_file import load_protocol
from Services.modbus.core.register_map import Reg, RegBlock, RegDW

_YAML_PATH = Path(__file__).resolve().parents[1] / "protocols" / "delta_v2.yaml"

W_MIN = -32767
W_MAX = 32767


@pytest.fixture(scope="module")
def raw_yaml() -> dict:
    """Сырой dict всего файла — доступ к секциям, которых `load_protocol` не видит.

    ``load_protocol`` строит DeviceProtocol только из name/kind/description/
    word_order/registers; секции constants/opcodes/errno/reasons/params/scenario/
    stop_levels читаем напрямую через yaml.safe_load.
    """
    return yaml.safe_load(_YAML_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def proto():
    """DeviceProtocol из `load_protocol` — регистры + word_order."""
    return load_protocol(_YAML_PATH)


# ─────────────────────── T0.1: загрузка ──────────────────────────────────────── #


def test_yaml_loads_and_loader_accepts(proto) -> None:
    """Файл грузится существующим загрузчиком; шапка совпадает с design."""
    assert proto.name == "delta_v2"
    assert proto.kind == "robot"
    assert proto.register_map.word_order == "little"
    assert len(proto.register_map.names()) > 0


# ─────────────────────── §3: регистры (Reg) ──────────────────────────────────── #

# (имя, адрес, signed) — литералы из protocol-spec.md §3.1-§3.4.
# TLM_ENC (DW, §3.4) сюда не входит: тип в спеке помечен просто "DW" без u16/s16 —
# см. отчёт, "расхождения/неоднозначности".
_REG_TABLE: list[tuple[str, int, bool]] = [
    # CMD, §3.1
    ("cmd_flag", 0x1000, False),
    ("cmd_seq", 0x1001, False),
    ("cmd_opcode", 0x1002, False),
    ("cmd_argc", 0x1003, False),
    # RES, §3.2
    ("res_seq", 0x1010, False),
    ("res_status", 0x1011, False),
    ("res_errno", 0x1012, False),
    ("res_rvalc", 0x1013, False),
    # Безопасность, §3.3
    ("hb_pc", 0x1020, False),
    ("stop_req", 0x1021, False),
    ("jog_lease", 0x1022, False),
    # TLM, §3.4 (Тип: u16 -> signed=False, s16 -> signed=True)
    ("tlm_proto_ver", 0x1040, False),
    ("tlm_fw_build", 0x1041, False),
    ("tlm_hb_robot", 0x1042, False),
    ("tlm_activity", 0x1043, False),
    ("tlm_x", 0x1044, True),
    ("tlm_y", 0x1045, True),
    ("tlm_z", 0x1046, True),
    ("tlm_rz", 0x1047, True),
    ("tlm_moving", 0x1048, False),
    ("tlm_servo", 0x1049, False),
    ("tlm_spd_pct", 0x104A, False),
    ("tlm_do_mask", 0x104B, False),
    ("tlm_belt_mms", 0x104E, True),
    ("tlm_wdg_state", 0x104F, False),
    ("tlm_ack_seq", 0x1050, False),
    ("tlm_done_seq", 0x1051, False),
    ("tlm_err_seq", 0x1052, False),
    ("tlm_errno_last", 0x1053, False),
    ("tlm_err_evt", 0x1054, False),
    ("tlm_err_count", 0x1055, False),
    ("tlm_sc_id", 0x1056, False),
    ("tlm_sc_total", 0x1057, False),
    ("tlm_sc_index", 0x1058, False),
    ("tlm_sc_done_n", 0x1059, False),
    ("tlm_miss_count", 0x105A, False),
    ("tlm_hand", 0x105B, False),
    ("tlm_stop_ack", 0x105C, False),
    ("tlm_cfg_epoch", 0x105D, False),
    ("tlm_cfg_pending", 0x105E, False),
    # PMIR, §3.5
    ("pmir_magic", 0x3080, False),
    ("pmir_crc", 0x3081, False),
    ("pmir_dict", 0x3082, False),
]


@pytest.mark.parametrize("name,address,signed", _REG_TABLE, ids=[r[0] for r in _REG_TABLE])
def test_register_address_signed_access(proto, name: str, address: int, signed: bool) -> None:
    """Каждый именованный одиночный регистр §3: address и signed 1:1 со спекой."""
    entry = proto.register_map.entry(name)
    assert isinstance(entry, Reg), f"{name}: ожидается Reg, получено {type(entry).__name__}"
    assert entry.address == address, f"{name}: address"
    assert entry.signed == signed, f"{name}: signed"


# ─────────────────────── §3: DW и блоки ──────────────────────────────────────── #


def test_register_dw_tlm_enc_address(proto) -> None:
    """TLM_ENC — DW на чётном адресе 0x104C (§3.4). Знаковость не пиним — см. отчёт."""
    entry = proto.register_map.entry("tlm_enc")
    assert isinstance(entry, RegDW), f"tlm_enc: ожидается RegDW, получено {type(entry).__name__}"
    assert entry.address == 0x104C


@pytest.mark.parametrize(
    "name,address,count",
    [
        ("cmd_args", 0x1004, 12),  # CMD_ARG0..ARG11, §3.1
        ("res_rvals", 0x1014, 8),  # RES_RVAL0..7, §3.2
        ("pmir", 0x3000, 128),  # PMIR-словарь, §3.5 (адрес = 0x3000 + id)
        ("sc_buf", 0x1400, 330),  # SC_CAP=55 * SC_STRIDE=6, §3.5/§7.1
    ],
)
def test_register_block_layout(proto, name: str, address: int, count: int) -> None:
    """Многослотовые области — type: block + count, по DESIGN."""
    entry = proto.register_map.entry(name)
    assert isinstance(entry, RegBlock), f"{name}: ожидается RegBlock, получено {type(entry).__name__}"
    assert entry.address == address, f"{name}: address"
    assert entry.count == count, f"{name}: count"


def test_vfd_mailbox_not_in_registers(proto) -> None:
    """Mailbox ПЧ 0x1200..0x121F заморожен и не входит в registers (владелец vfd_comm, §3.5)."""
    for name in proto.register_map.names():
        entry = proto.register_map.entry(name)
        if isinstance(entry, Reg):
            width = 1
        elif isinstance(entry, RegDW):
            width = 2
        else:
            width = entry.count
        start, end = entry.address, entry.address + width  # [start, end)
        assert not (start < 0x1220 and 0x1200 < end), (
            f"{name} [0x{start:04X}..0x{end - 1:04X}] пересекает mailbox ПЧ 0x1200..0x121F"
        )


# ─────────────────────── §5: опкоды ──────────────────────────────────────────── #

# (имя, code, argc, busy) — литералы из protocol-spec.md §5.
_OPCODES_TABLE: list[tuple[str, int, int, str]] = [
    ("PING", 0x01, 0, "allow"),
    ("CLEAR_ERR", 0x02, 0, "allow"),
    ("PTP_MOVE", 0x10, 6, "deny"),
    ("HOME", 0x11, 1, "deny"),
    ("JOG_STEP", 0x12, 5, "deny"),
    ("JOG_CONT", 0x13, 2, "deny"),
    ("CVT_JOB", 0x20, 10, "deny"),
    ("SC_RUN", 0x30, 3, "deny"),
    ("SERVO", 0x41, 1, "deny"),
    ("DO_SET", 0x42, 2, "deny"),
    ("PARAM_SET", 0x50, 2, "by_class"),
    ("PARAM_GET", 0x51, 1, "allow"),
    ("PARAM_APPLY", 0x52, 0, "deny"),
]


@pytest.mark.parametrize("name,code,argc,busy", _OPCODES_TABLE, ids=[o[0] for o in _OPCODES_TABLE])
def test_opcodes_table(raw_yaml, name: str, code: int, argc: int, busy: str) -> None:
    """§5: code/argc/busy каждого опкода — точное совпадение со спекой."""
    opcodes = raw_yaml["opcodes"]
    assert name in opcodes, f"опкод {name} отсутствует в YAML"
    row = opcodes[name]
    assert row["code"] == code, f"{name}: code"
    assert row["argc"] == argc, f"{name}: argc"
    assert row["busy"] == busy, f"{name}: busy"


def test_opcodes_set_is_exactly_thirteen(raw_yaml) -> None:
    """§5 перечисляет ровно 13 опкодов — ни лишних, ни пропущенных."""
    expected_names = {row[0] for row in _OPCODES_TABLE}
    actual_names = set(raw_yaml["opcodes"])
    assert actual_names == expected_names, (
        f"лишние: {actual_names - expected_names}, отсутствуют: {expected_names - actual_names}"
    )


# ─────────────────────── §6: errno ───────────────────────────────────────────── #

# (имя, code, kind, точный русский текст GUI) — литералы из protocol-spec.md §6.
_ERRNO_TABLE: list[tuple[str, int, str, str]] = [
    ("E_OK", 0, "none", "ОК"),
    ("E_BAD_OPCODE", 1, "sync", "Неизвестная команда"),
    ("E_BAD_ARGC", 2, "sync", "Неверное число аргументов"),
    ("E_RANGE", 3, "sync", "Значение или цель вне допустимого диапазона (rval0 — причина)"),
    ("E_BUSY", 4, "sync", "Робот занят другой командой"),
    ("E_BAD_PARAM", 5, "sync", "Неизвестный параметр"),
    ("E_NO_SERVO", 6, "sync", "Серво выключено — движение невозможно"),
    ("E_SC_COUNT", 7, "sync", "Недопустимое число точек или смещение в буфере"),
    ("E_SC_RECORD", 8, "sync", "Ошибка в точке сценария (rval0 — индекс, rval1 — причина)"),
    ("E_BUF_SHORT", 9, "sync", "Буфер сценария прочитан не полностью"),
    ("E_WDG_TIMEOUT", 10, "async", "Пропала связь с ПК — лента и движение остановлены"),
    ("E_MOTION_FAULT", 11, "async", "Контроллер движения в ошибке"),
    ("E_ZONE_TRIP", 12, "async", "Объект вышел из рабочей зоны ленты"),
    ("E_ABORTED", 13, "async", "Движение прервано стопом"),
    ("E_INTERNAL", 14, "both", "Внутренняя ошибка прошивки"),
    ("E_CFG_PENDING", 15, "sync", "Параметры приняты, но не применены — выполните «Применить»"),
    ("E_VFD_LINK", 16, "async", "ПЧ не отвечает по RS-485"),
]


@pytest.mark.parametrize("name,code,kind,text", _ERRNO_TABLE, ids=[e[0] for e in _ERRNO_TABLE])
def test_errno_table(raw_yaml, name: str, code: int, kind: str, text: str) -> None:
    """§6: code/kind/точный русский текст каждого errno — 17 строк."""
    errno = raw_yaml["errno"]
    assert name in errno, f"errno {name} отсутствует в YAML"
    row = errno[name]
    assert row["code"] == code, f"{name}: code"
    assert row["kind"] == kind, f"{name}: kind"
    assert row["text"] == text, f"{name}: text"


def test_errno_set_is_exactly_seventeen(raw_yaml) -> None:
    """§6 перечисляет ровно 17 кодов ошибок."""
    expected_names = {row[0] for row in _ERRNO_TABLE}
    actual_names = set(raw_yaml["errno"])
    assert actual_names == expected_names, (
        f"лишние: {actual_names - expected_names}, отсутствуют: {expected_names - actual_names}"
    )


# ─────────────────────── §6: коды причины (reasons) ──────────────────────────── #

# (имя, code) — code пинуется литералом; текст пинуется мягко (непустая строка +
# ключевое слово), спека не требует "exact" текста для reasons (в отличие от errno).
_REASONS_TABLE: list[tuple[str, int]] = [
    ("R_KIND", 1),
    ("R_ACTION", 2),
    ("R_APARAM", 3),
    ("R_OUT_OF_ZONE", 4),
    ("R_DEAD_ZONE", 5),
    ("R_LAST_PASS", 6),
    ("R_HAND", 7),
    ("R_JOG_TOO_LONG", 8),
]


@pytest.mark.parametrize("name,code", _REASONS_TABLE, ids=[r[0] for r in _REASONS_TABLE])
def test_reasons_scenario_stop_levels(raw_yaml, name: str, code: int) -> None:
    """§6 «Коды причины»: код 1..8 точно; текст непуст (см. докстринг про мягкость)."""
    reasons = raw_yaml["reasons"]
    assert name in reasons, f"reason {name} отсутствует в YAML"
    row = reasons[name]
    assert row["code"] == code, f"{name}: code"
    assert isinstance(row.get("text"), str) and row["text"].strip(), f"{name}: text пуст"


def test_scenario_section(raw_yaml) -> None:
    """§7.1: stride/record/kinds/actions — литералы из раскладки записи буфера."""
    scenario = raw_yaml["scenario"]
    assert scenario["stride"] == 6
    assert scenario["record"] == ["x", "y", "z", "rz", "op", "aparam"]
    assert scenario["kinds"] == {"LINE": 0, "LINE_PASS": 1, "JOINT": 2}
    assert scenario["actions"] == {
        "NONE": 0,
        "DO_ON": 1,
        "DO_OFF": 2,
        "DELAY_MS": 3,
        "SPEED_PCT": 4,
        "ACCEL": 5,
        "ACCUR": 6,
    }


def test_stop_levels_section(raw_yaml) -> None:
    """§8: уровни стопа SOFT/HARD/HALT = 1/2/3."""
    assert raw_yaml["stop_levels"] == {"SOFT": 1, "HARD": 2, "HALT": 3}


# ─────────────────────── constants ───────────────────────────────────────────── #


def test_constants_table(raw_yaml) -> None:
    """`constants:` — базы блоков и лимиты протокола, литералы из DESIGN/§3/§7/§12."""
    constants = raw_yaml["constants"]
    expected = {
        "PROTO_VER": 0x0200,
        "CMD_BASE": 0x1000,
        "RES_BASE": 0x1010,
        "SAFETY_BASE": 0x1020,
        "TLM_BASE": 0x1040,
        "SC_BASE": 0x1400,
        "PMIR_BASE": 0x3000,
        "PMIR_FALLBACK_BASE": 0x1300,
        "VFD_BASE": 0x1200,
        "SC_STRIDE": 6,
        "SC_CAP": 55,
        "WRITE_CHUNK": 30,
        "READ_MAX": 125,
        "W_MIN": W_MIN,
        "W_MAX": W_MAX,
        "PMIR_MAGIC_VALUE": 0x5632,
    }
    for key, value in expected.items():
        assert constants.get(key) == value, f"constants.{key}"
    assert constants["gate1_constants"] == ["PMIR_BASE", "SC_CAP"]


# ─────────────────────── §11.3: словарь параметров ───────────────────────────── #

# (id, name, min, max, default, apply, group, gate1) — литералы params.md §11.3.
# "зона"/"—" -> полный диапазон слова знаковый (-32767..32767, координаты/углы).
# "как SCM_FreePort" (VFD_BAUD/FRAME/MODE) интерпретирован как безнаковый полный
# диапазон (0..32767) — это МОЯ интерпретация, не буквальный факт спеки, см. отчёт.
_PARAMS_TABLE: list[tuple[int, str, int, int, int | None, str, int, bool]] = [
    # motion (group 0)
    (0, "P_SPD_DEFAULT", 1, 100, 80, "live", 0, False),
    (1, "P_SPD_JOG", 1, 100, 30, "live", 0, False),
    (2, "P_SPD_L", 10, 3000, 1500, "idle", 0, False),
    (3, "P_ACC_L", 100, 50000, 25000, "idle", 0, False),
    (4, "P_SPD_J", 1, 100, 70, "idle", 0, False),
    (5, "P_ACC_J", 1, 100, 100, "idle", 0, False),
    (6, "P_OVERLAP", 1, 100, 5, "idle", 0, False),
    (7, "P_ACCUR_DEFAULT", 0, 1, 0, "idle", 0, False),
    (8, "P_JOG_MAX", 1, 5000, 2000, "idle", 0, False),
    (9, "P_HAND", 0, 1, 1, "idle", 0, True),
    (10, "P_JOG_CONT_MAX", 1, 250, 50, "live", 0, False),
    (11, "P_JOG_LEASE_MS", 300, 2000, 300, "live", 0, False),
    (12, "P_DEC_STOP", 1000, 25000, 25000, "idle", 0, False),
    # points (group 1) — "зона" -> полный знаковый диапазон слова
    (16, "P_HOME_X", W_MIN, W_MAX, 3000, "idle", 1, False),
    (17, "P_HOME_Y", W_MIN, W_MAX, -2100, "idle", 1, False),
    (18, "P_HOME_Z", W_MIN, W_MAX, -400, "idle", 1, False),
    (19, "P_HOME_RZ", W_MIN, W_MAX, -1000, "idle", 1, False),
    (20, "P_PLACE_X", W_MIN, W_MAX, 4500, "idle", 1, False),
    (21, "P_PLACE_Y", W_MIN, W_MAX, -3000, "idle", 1, False),
    (22, "P_PLACE_Z", W_MIN, W_MAX, -900, "idle", 1, False),
    (23, "P_PLACE_RZ", W_MIN, W_MAX, -1000, "idle", 1, False),
    (24, "P_PICK_Z", W_MIN, W_MAX, -1000, "idle", 1, False),
    (25, "P_PICK_RZ", W_MIN, W_MAX, -1000, "idle", 1, False),
    # cvt (group 2)
    (32, "P_GRIP_MS", 0, 5000, 400, "idle", 2, False),
    (33, "P_ZONE_MIN", 0, 32767, 1200, "idle", 2, False),
    (34, "P_ZONE_MAX", 0, 32767, 5000, "idle", 2, False),
    (35, "P_BELT_FACTOR", 1, 65535, 14447, "reinit", 2, False),  # см. test_params_u16_over_w_range
    (36, "P_BELT_DIR", 0, 3, 1, "reinit", 2, False),
    (37, "P_TRIG_X", W_MIN, W_MAX, 3346, "reinit", 2, False),
    (38, "P_TRIG_Y", W_MIN, W_MAX, -3811, "reinit", 2, False),
    (39, "P_ZONE_END_X", W_MIN, W_MAX, 3346, "reinit", 2, False),
    (40, "P_ZONE_END_Y", W_MIN, W_MAX, -2000, "reinit", 2, False),
    (41, "P_NG_RADIUS", 0, 32767, 200, "reinit", 2, False),
    (42, "P_DO_GRIP_CH", 1, 16, 1, "idle", 2, False),
    # workspace (group 3)
    (48, "P_WS_R_MIN", 0, 32767, 1000, "idle", 3, True),
    (49, "P_WS_R_MAX", 0, 32767, 6000, "idle", 3, True),
    (50, "P_WS_Z_MIN", W_MIN, W_MAX, -1500, "idle", 3, True),
    (51, "P_WS_Z_MAX", W_MIN, W_MAX, 0, "idle", 3, True),
    (52, "P_WS_RZ_MIN", W_MIN, W_MAX, -3600, "idle", 3, True),
    (53, "P_WS_RZ_MAX", W_MIN, W_MAX, 3600, "idle", 3, True),
    (54, "P_WS_BOX_EN", 0, 1, 0, "idle", 3, False),
    (55, "P_WS_X_MIN", W_MIN, W_MAX, -6000, "idle", 3, False),
    (56, "P_WS_X_MAX", W_MIN, W_MAX, 6000, "idle", 3, False),
    (57, "P_WS_Y_MIN", W_MIN, W_MAX, -6000, "idle", 3, False),
    (58, "P_WS_Y_MAX", W_MIN, W_MAX, 6000, "idle", 3, False),
    # P_WS_ANG_MIN/MAX — default по паспорту модели, ОТКРЫТЫЙ вопрос владельцу;
    # проверяются отдельно в test_params_ws_ang_min_max, default=None здесь.
    (59, "P_WS_ANG_MIN", -1800, 1800, None, "idle", 3, True),
    (60, "P_WS_ANG_MAX", -1800, 1800, None, "idle", 3, True),
    # vfd (group 4)
    (64, "P_VFD_PROFILE", 0, 0, 0, "reinit", 4, False),
    (65, "P_VFD_SLAVE", 1, 247, 1, "reinit", 4, False),
    (66, "P_VFD_BAUD", 0, 32767, 2, "reinit", 4, False),
    (67, "P_VFD_FRAME", 0, 32767, 13, "reinit", 4, False),
    (68, "P_VFD_MODE", 0, 32767, 17, "reinit", 4, False),
    (69, "P_VFD_POLL_MS", 50, 5000, 300, "live", 4, False),
    (70, "P_VFD_RX_TRIES", 1, 50, 8, "idle", 4, False),
    (71, "P_VFD_LINK_FAILS", 1, 100, 5, "idle", 4, False),
    # system (group 6)
    (96, "P_WDG_TIMEOUT_MS", 0, 60000, 3000, "live", 6, False),
    (97, "P_TLM_EVERY", 1, 100, 5, "live", 6, False),
    (98, "P_CONFIG_EPOCH", 0, 65535, 0, "live", 6, False),  # см. test_params_u16_over_w_range
]

_U16_OVER_W_RANGE_IDS = {35, 98}  # P_BELT_FACTOR, P_CONFIG_EPOCH


@pytest.mark.parametrize(
    "pid,name,pmin,pmax,default,apply,group,gate1",
    _PARAMS_TABLE,
    ids=[f"{p[0]}_{p[1]}" for p in _PARAMS_TABLE],
)
def test_params_dictionary(
    raw_yaml, pid: int, name: str, pmin: int, pmax: int, default, apply: str, group: int, gate1: bool
) -> None:
    """§11.3: id/min/max/default/apply/group каждого параметра — литералы из таблицы."""
    params = raw_yaml["params"]
    assert name in params, f"параметр {name} отсутствует в YAML"
    row = params[name]
    assert row["id"] == pid, f"{name}: id"
    assert pid // 16 == group, f"{name}: id//16 должно быть {group}"
    assert row.get("group") == group, f"{name}: group"
    assert row["min"] == pmin, f"{name}: min"
    assert row["max"] == pmax, f"{name}: max"
    assert row["apply"] == apply, f"{name}: apply"
    if default is not None:
        assert row["default"] == default, f"{name}: default"
        assert pmin <= row["default"] <= pmax, f"{name}: default вне [min, max]"
    if gate1:
        assert row.get("gate1") is True, f"{name}: ожидается gate1: true"
    else:
        assert not row.get("gate1"), f"{name}: gate1 не ожидался"


def test_params_ws_ang_min_max_default_exists_and_ordered(raw_yaml) -> None:
    """P_WS_ANG_MIN/MAX: default — открытый вопрос владельцу (модель робота, plan.md §9).

    Пин только то, что известно сейчас: default существует, лежит в -1800..1800,
    MIN < MAX. Литеральное значение default НЕ пиним — его нет в params.md.
    """
    params = raw_yaml["params"]
    ang_min = params["P_WS_ANG_MIN"]["default"]
    ang_max = params["P_WS_ANG_MAX"]["default"]
    assert ang_min is not None and ang_max is not None
    assert -1800 <= ang_min <= 1800
    assert -1800 <= ang_max <= 1800
    assert ang_min < ang_max


def test_params_ids_are_unique(raw_yaml) -> None:
    """Id параметров стабильны и уникальны навсегда (params.md §11.1)."""
    ids = [row["id"] for row in raw_yaml["params"].values()]
    assert len(ids) == len(set(ids)), "дублирующиеся id в словаре параметров"


@pytest.mark.xfail(
    strict=False,
    reason="contract contradiction: W range (-32767..32767) vs заявленный max=65535 "
    "для P_BELT_FACTOR/P_CONFIG_EPOCH — открытый вопрос владельцу на GATE-0",
)
@pytest.mark.parametrize(
    "pid,name,expected_max",
    [(35, "P_BELT_FACTOR", 65535), (98, "P_CONFIG_EPOCH", 65535)],
    ids=["P_BELT_FACTOR", "P_CONFIG_EPOCH"],
)
def test_params_u16_over_w_range(raw_yaml, pid: int, name: str, expected_max: int) -> None:
    """params.md заявляет max=65535 для этих двух — вне W_MAX=32767 (§3 «Слово W»).

    xfail(strict=False): если разработчик уже привёл словарь в соответствие
    с диапазоном W (например, урезал max до 32767), тест обязан начать падать
    по-другому (не xfail) — сигнал вернуться к GATE-0.
    """
    row = raw_yaml["params"][name]
    assert row["id"] == pid
    assert row["max"] == expected_max
    assert row["max"] > W_MAX, f"{name}: max должен превышать W_MAX, иначе противоречие снято"


# ─────────────────────── структурные инварианты ──────────────────────────────── #


def test_structural_invariant_dw_on_even_address(raw_yaml) -> None:
    """Все type: dw в registers — на чётном адресе."""
    for name, row in raw_yaml["registers"].items():
        if row.get("type") == "dw":
            assert row["address"] % 2 == 0, f"{name}: dw на нечётном адресе 0x{row['address']:04X}"


def test_structural_invariant_no_overlap_and_ranges(raw_yaml) -> None:
    """Регистры не пересекаются, не задевают VFD-mailbox, лежат в 0x1000..0x1FFF/0x3000..0x3FFF."""
    spans: list[tuple[int, int, str]] = []
    for name, row in raw_yaml["registers"].items():
        rtype = row["type"]
        addr = row["address"]
        width = 2 if rtype == "dw" else (row["count"] if rtype == "block" else 1)
        end = addr + width  # [addr, end)
        spans.append((addr, end, name))
        in_user_space = (0x1000 <= addr and end <= 0x2000) or (0x3000 <= addr and end <= 0x4000)
        assert in_user_space, f"{name} [0x{addr:04X}..0x{end - 1:04X}] вне 0x1000..0x1FFF / 0x3000..0x3FFF"
        assert not (addr < 0x1220 and 0x1200 < end), f"{name} пересекает VFD-mailbox 0x1200..0x121F"

    spans.sort()
    for (start_a, end_a, name_a), (start_b, end_b, name_b) in zip(spans, spans[1:]):
        assert end_a <= start_b, f"перекрытие {name_a} [..0x{end_a - 1:04X}] и {name_b} [0x{start_b:04X}..]"


def test_structural_invariant_tlm_fits_block(raw_yaml) -> None:
    """Вся TLM-плоскость лежит в 0x1040..0x105F (§3.4)."""
    for name, row in raw_yaml["registers"].items():
        if name.startswith("tlm_"):
            width = 2 if row["type"] == "dw" else 1
            assert 0x1040 <= row["address"] and row["address"] + width - 1 <= 0x105F, f"{name} вне TLM-плоскости"


def test_structural_invariant_sc_buf_ends_at_0x1549(raw_yaml) -> None:
    """SC-буфер: SC_CAP(55) * SC_STRIDE(6) = 330 слов, 0x1400..0x1549 (§3.5)."""
    sc_buf = raw_yaml["registers"]["sc_buf"]
    assert sc_buf["address"] == 0x1400
    assert sc_buf["address"] + sc_buf["count"] - 1 == 0x1549


def test_structural_invariant_pmir_tail_addresses(raw_yaml) -> None:
    """PMIR_MAGIC/CRC/DICT — 0x3080..0x3082, сразу после pmir-блока (§3.5)."""
    regs = raw_yaml["registers"]
    assert regs["pmir"]["address"] == 0x3000
    assert regs["pmir"]["count"] == 128
    assert regs["pmir_magic"]["address"] == 0x3080
    assert regs["pmir_crc"]["address"] == 0x3081
    assert regs["pmir_dict"]["address"] == 0x3082


def test_structural_invariant_max_param_id_under_128(raw_yaml) -> None:
    """Максимальный id параметра < 128 — иначе не влезает в PMIR-словарь (0x3000+id, 128 слов)."""
    max_id = max(row["id"] for row in raw_yaml["params"].values())
    assert max_id < 128


# ─────────────────────── gate1-метки ──────────────────────────────────────────── #


def test_gate1_markers(raw_yaml) -> None:
    """gate1: true — на каждой ⚠️-строке params.md плюс P_HAND и P_WS_ANG_MIN/MAX."""
    expected_gate1_ids = {9, 48, 49, 50, 51, 52, 53, 59, 60}
    params = raw_yaml["params"]
    actual_gate1_ids = {row["id"] for row in params.values() if row.get("gate1") is True}
    assert actual_gate1_ids == expected_gate1_ids, (
        f"лишние gate1: {actual_gate1_ids - expected_gate1_ids}, "
        f"пропущенные gate1: {expected_gate1_ids - actual_gate1_ids}"
    )


# ─────────────────────── «боевые» дефолты ────────────────────────────────────── #


def test_combat_defaults(raw_yaml) -> None:
    """Дефолты безопасности/поведения ленты — литералы, которые нельзя перепутать."""
    params = raw_yaml["params"]
    assert params["P_WDG_TIMEOUT_MS"]["default"] == 3000
    assert params["P_BELT_FACTOR"]["default"] == 14447
    assert params["P_DEC_STOP"]["default"] == 25000
