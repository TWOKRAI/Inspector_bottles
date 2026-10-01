"""Схемные инварианты `Services/robot_comm/protocols/delta_v2.yaml` (T1.2).

Каждый инвариант — маленькая функция `check_*(doc) -> list[str]` над РАЗОБРАННЫМ dict: пустой
список = инвариант держится. Одна и та же функция гоняется на настоящем файле
(`test_*` ниже) и на испорченной копии в tmp_path (`test_corruption_is_caught`) — так видно, что
проверка умеет падать, а не «зелёная по определению».

Не дублирует `test_delta_v2_contract.py` / `test_delta_v2_yaml_shape.py`. Уже покрыто ими (пропущено):
  - VFD-mailbox 0x1200..0x121F не пересекается ни с одним регистром — `test_vfd_mailbox_not_in_registers`
    и `test_structural_invariant_no_overlap_and_ranges` (обе на литералах 0x1200/0x1220);
  - DW на чётном адресе, перекрытия/диапазоны блоков, TLM в 0x1040..0x105F, конец SC-буфера 0x1549,
    хвост PMIR, уникальность id параметров, max id < 128, u16 над W, gate1-метки, argc == len(args).
Здесь — остальное из брифа T1.2. Ожидаемые значения — литералы, а не производные от загруженного
YAML; константы из `constants:` берутся только как «что заявлено», и рядом стоит проверка литерала.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from Services.robot_comm.tests import test_delta_v2_contract as _existing

_TESTS_DIR = Path(__file__).resolve().parent
_YAML_PATH = _TESTS_DIR.parent / "protocols" / "delta_v2.yaml"
_SNAPSHOT_PATH = _TESTS_DIR / "param_ids.snapshot"

# Знаковое слово W: −32768 запрещён (RL 12-2), значит s16-поле обязано иметь min >= −32767.
_S16_FLOOR = -32767
_ARGC_MAX = 12  # CMD_ARG0..ARG11


# ─────────────────────────── чтение ──────────────────────────────────────────── #


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load_snapshot(path: Path) -> dict[int, str]:
    """`id name` по строке -> {id: name}. Пустые строки пропускаются, комментариев нет."""
    snap: dict[int, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        pid, name = line.split(None, 1)
        snap[int(pid)] = name.strip()
    return snap


def _width(row: dict) -> int:
    rtype = row["type"]
    return 2 if rtype == "dw" else (row["count"] if rtype == "block" else 1)


# ─────────────────────────── инварианты ──────────────────────────────────────── #


def check_write_within_chunk(doc: dict) -> list[str]:
    """Одна клиентская запись <= WRITE_CHUNK слов.

    Записи клиента: mailbox CMD (одним FC16, флаг — отдельно) — его размах от CMD_BASE до конца
    последнего регистра в [CMD_BASE, RES_BASE); любой другой rw-блок кроме sc_buf (тот пишется
    кусками по WRITE_CHUNK по определению) обязан влезать в один кусок.

    Размах считается от CMD_BASE (слово флага включено), а FC16 пишет с CMD_BASE + 1 — проверка строже
    реальной на одно слово, это осознанный запас.
    """
    c = doc["constants"]
    chunk = c["WRITE_CHUNK"]
    bad: list[str] = []
    cmd_rows = {n: r for n, r in doc["registers"].items() if c["CMD_BASE"] <= r["address"] < c["RES_BASE"]}
    span = max(r["address"] + _width(r) for r in cmd_rows.values()) - c["CMD_BASE"]
    if span > chunk:
        bad.append(f"mailbox CMD пишется {span} слов > WRITE_CHUNK={chunk}")
    for name, row in doc["registers"].items():
        if row["type"] == "block" and row["access"] == "rw" and name != "sc_buf" and row["count"] > chunk:
            bad.append(f"{name}: rw-блок {row['count']} слов > WRITE_CHUNK={chunk}")
    return bad


def check_sc_chunk_is_whole_records(doc: dict) -> list[str]:
    """Кусок записи буфера сценария кратен SC_STRIDE — запись не рвётся посреди слота.

    Удобство ПК (кусок не рвёт слот), не правило протокола — protocol-spec этого не требует.
    """
    c = doc["constants"]
    if c["WRITE_CHUNK"] % c["SC_STRIDE"] != 0:
        return [f"WRITE_CHUNK={c['WRITE_CHUNK']} не кратен SC_STRIDE={c['SC_STRIDE']}"]
    return []


def check_tlm_read_within_max(doc: dict) -> list[str]:
    """Вся TLM-плоскость читается одним FC3: размах от TLM_BASE до конца последнего tlm_* <= READ_MAX.

    Выбор по префиксу `tlm_`, а не по адресу: зона TLM 0x1040..0x107F — 64 слова < READ_MAX=125, адресный
    выбор с верхней границей делает проверку вакуумной (замечание m4 ревью T1.2 отклонено по этой причине);
    проверка ловит `tlm_`-регистр, вынесенный за зону.
    """
    c = doc["constants"]
    tlm = [r for n, r in doc["registers"].items() if n.startswith("tlm_")]
    span = max(r["address"] + _width(r) for r in tlm) - c["TLM_BASE"]
    return [f"TLM читается {span} слов > READ_MAX={c['READ_MAX']}"] if span > c["READ_MAX"] else []


def check_pmir_read_within_max(doc: dict) -> list[str]:
    """PMIR читается от PMIR_BASE до самого старшего id включительно: id_max+1 <= READ_MAX и влезает в блок."""
    c = doc["constants"]
    span = max(r["id"] for r in doc["params"].values()) + 1
    bad: list[str] = []
    if span > c["READ_MAX"]:
        bad.append(f"PMIR читается {span} слов > READ_MAX={c['READ_MAX']}")
    if span > doc["registers"]["pmir"]["count"]:
        bad.append(f"PMIR читается {span} слов > блока pmir.count={doc['registers']['pmir']['count']}")
    return bad


def check_sc_capacity_inside_block(doc: dict) -> list[str]:
    """SC_BASE + SC_CAP*SC_STRIDE лежит внутри блока sc_buf, и SC_BASE — это его адрес."""
    c = doc["constants"]
    buf = doc["registers"]["sc_buf"]
    bad: list[str] = []
    if buf["address"] != c["SC_BASE"]:
        bad.append(f"sc_buf.address=0x{buf['address']:04X} != SC_BASE=0x{c['SC_BASE']:04X}")
    end = c["SC_BASE"] + c["SC_CAP"] * c["SC_STRIDE"]  # [SC_BASE, end)
    if end > buf["address"] + buf["count"]:
        bad.append(f"SC_BASE+SC_CAP*SC_STRIDE=0x{end:04X} за концом sc_buf 0x{buf['address'] + buf['count']:04X}")
    return bad


def check_param_ids_stable(doc: dict, snapshot: dict[int, str]) -> list[str]:
    """Каждая пара (id, имя) из снимка на месте; НОВЫЕ id допустимы."""
    current = {row["id"]: name for name, row in doc["params"].items()}
    bad: list[str] = []
    for pid, name in sorted(snapshot.items()):
        if pid not in current:
            bad.append(f"id {pid} ({name}) пропал")
        elif current[pid] != name:
            bad.append(f"id {pid}: было {name}, стало {current[pid]}")
    return bad


def check_argc_max(doc: dict) -> list[str]:
    """argc каждого опкода <= числа слотов CMD_ARG (12) — заявленного блоком cmd_args."""
    slots = doc["registers"]["cmd_args"]["count"]
    return [f"{op}: argc={row['argc']} > {slots}" for op, row in doc["opcodes"].items() if row["argc"] > slots]


def check_errno_codes_unique(doc: dict) -> list[str]:
    return _duplicates(doc["errno"])


def check_reason_codes_unique(doc: dict) -> list[str]:
    return _duplicates(doc["reasons"])


def _duplicates(section: dict) -> list[str]:
    seen: dict[int, str] = {}
    bad: list[str] = []
    for name, row in section.items():
        if row["code"] in seen:
            bad.append(f"код {row['code']} у {seen[row['code']]} и {name}")
        seen.setdefault(row["code"], name)
    return bad


def check_param_default_in_range(doc: dict) -> list[str]:
    return [
        f"{name}: default={row['default']} вне [{row['min']}, {row['max']}]"
        for name, row in doc["params"].items()
        if not row["min"] <= row["default"] <= row["max"]
    ]


def check_no_s16_admits_minus_32768(doc: dict) -> list[str]:
    """Знаковое поле с объявленным диапазоном не допускает −32768.

    Параметры: signed: true -> min >= −32767. Регистры: signed-регистр допускается только без
    объявленного диапазона (сейчас ни у одного регистра min/max нет — см. отчёт), а если он
    появится, min обязан быть >= −32767 тем же правилом.
    """
    bad = [
        f"param {name}: min={row['min']} допускает −32768"
        for name, row in doc["params"].items()
        if row["signed"] and row["min"] < _S16_FLOOR
    ]
    bad += [
        f"reg {name}: min={row['min']} допускает −32768"
        for name, row in doc["registers"].items()
        if row.get("signed") and "min" in row and row["min"] < _S16_FLOOR
    ]
    return bad


# ─────────────────────────── фикстуры ────────────────────────────────────────── #


@pytest.fixture(scope="module")
def doc() -> dict:
    return _load(_YAML_PATH)


@pytest.fixture(scope="module")
def snapshot() -> dict[int, str]:
    return _load_snapshot(_SNAPSHOT_PATH)


# ─────────────────────────── инварианты на настоящем файле ───────────────────── #


@pytest.mark.parametrize(
    "check",
    [
        check_write_within_chunk,
        check_sc_chunk_is_whole_records,
        check_tlm_read_within_max,
        check_pmir_read_within_max,
        check_sc_capacity_inside_block,
        check_argc_max,
        check_errno_codes_unique,
        check_reason_codes_unique,
        check_param_default_in_range,
        check_no_s16_admits_minus_32768,
    ],
    ids=lambda f: f.__name__,
)
def test_invariant_holds_on_real_yaml(doc: dict, check: Callable[[dict], list[str]]) -> None:
    assert check(doc) == []


def test_param_ids_stable_against_snapshot(doc: dict, snapshot: dict[int, str]) -> None:
    assert check_param_ids_stable(doc, snapshot) == []


# ─────────────────────────── литералы констант ───────────────────────────────── #


@pytest.mark.parametrize(
    "key,literal",
    [("WRITE_CHUNK", 30), ("READ_MAX", 125), ("SC_STRIDE", 6), ("SC_CAP", 55)],
)
def test_limit_constant_equals_literal(doc: dict, key: str, literal: int) -> None:
    assert doc["constants"][key] == literal


def test_cmd_args_block_has_twelve_slots(doc: dict) -> None:
    assert doc["registers"]["cmd_args"]["count"] == _ARGC_MAX


def test_no_opcode_exceeds_twelve_args_literal(doc: dict) -> None:
    """argc <= 12 против литерала, а не против cmd_args.count (тот проверяется отдельно выше)."""
    assert max(row["argc"] for row in doc["opcodes"].values()) <= 12


# ─────────────────────────── снимок id ───────────────────────────────────────── #


def test_snapshot_is_well_formed(snapshot: dict[int, str]) -> None:
    """Снимок непуст (иначе проверка стабильности вакуумна), без дублей id и имён, отсортирован по id.

    Новый параметр -> добавить строку `id name` в param_ids.snapshot.
    """
    lines = [ln for ln in _SNAPSHOT_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()]
    ids = [int(ln.split(None, 1)[0]) for ln in lines]
    assert len(ids) >= 58
    assert ids == sorted(set(ids))
    assert len(set(snapshot.values())) == len(snapshot)


def test_new_param_id_does_not_break_snapshot(doc: dict, snapshot: dict[int, str]) -> None:
    """Добавление НОВОГО id (в свободный слот 127) снимок не ломает."""
    extended = copy.deepcopy(doc)
    extended["params"]["P_NEW_FOR_TEST"] = {**doc["params"]["P_SPD_JOG"], "id": 127}
    assert check_param_ids_stable(extended, snapshot) == []


# ─────────────────────────── демонстрация: инварианты умеют падать ───────────── #


def _overlap_via_existing_test(doc: dict) -> list[str]:
    """Существующий структурный тест (принимает dict) как check-функция — без копирования тела."""
    try:
        _existing.test_structural_invariant_no_overlap_and_ranges(doc)
    except AssertionError as exc:
        return [str(exc)]
    return []


def _dw_even_via_existing_test(doc: dict) -> list[str]:
    try:
        _existing.test_structural_invariant_dw_on_even_address(doc)
    except AssertionError as exc:
        return [str(exc)]
    return []


def _snapshot_check(doc: dict) -> list[str]:
    return check_param_ids_stable(doc, _load_snapshot(_SNAPSHOT_PATH))


def _m_shift_into_vfd(d: dict) -> None:
    d["registers"]["res_seq"]["address"] = 0x1205  # в VFD-mailbox


def _m_shift_into_cmd(d: dict) -> None:
    d["registers"]["res_seq"]["address"] = 0x1001  # в чужой блок (CMD)


def _m_odd_dw(d: dict) -> None:
    d["registers"]["tlm_enc"]["address"] = 0x104D


def _m_cmd_args_40(d: dict) -> None:
    d["registers"]["cmd_args"]["count"] = 40


def _m_write_chunk_not_multiple(d: dict) -> None:
    d["constants"]["WRITE_CHUNK"] = 31


def _m_tlm_far(d: dict) -> None:
    d["registers"]["tlm_far"] = {**d["registers"]["tlm_x"], "address": 0x10C0}


def _m_pmir_id_125(d: dict) -> None:
    d["params"]["P_SPD_JOG"]["id"] = 125  # 126 слов > READ_MAX=125


def _m_sc_cap_60(d: dict) -> None:
    d["constants"]["SC_CAP"] = 60  # 360 слов в блоке на 330


def _m_sc_base_moved(d: dict) -> None:
    d["constants"]["SC_BASE"] = 0x1410


def _m_rename_param(d: dict) -> None:
    d["params"]["P_SPD_L_RENAMED"] = d["params"].pop("P_SPD_L")


def _m_drop_param(d: dict) -> None:
    del d["params"]["P_SPD_JOG"]


def _m_id_swap(d: dict) -> None:
    d["params"]["P_SPD_DEFAULT"]["id"], d["params"]["P_SPD_JOG"]["id"] = 1, 0


def _m_argc_13(d: dict) -> None:
    d["opcodes"]["PTP_MOVE"]["argc"] = 13


def _m_dup_errno(d: dict) -> None:
    d["errno"]["E_BUSY"]["code"] = 3  # как E_RANGE


def _m_dup_reason(d: dict) -> None:
    d["reasons"]["R_HAND"]["code"] = 6  # как R_LAST_PASS


def _m_default_above(d: dict) -> None:
    d["params"]["P_SPD_DEFAULT"]["default"] = 101


def _m_default_below(d: dict) -> None:
    d["params"]["P_SPD_L"]["default"] = 9


def _m_s16_min(d: dict) -> None:
    d["params"]["P_HOME_X"]["min"] = -32768


def _m_signed_reg_with_range(d: dict) -> None:
    d["registers"]["tlm_x"]["min"] = -32768


# (id кейса, инвариант, порча)
_CORRUPTIONS: list[tuple[str, Callable[[dict], list[str]], Callable[[dict], None]]] = [
    ("reg_into_vfd_block", _overlap_via_existing_test, _m_shift_into_vfd),
    ("reg_into_other_block", _overlap_via_existing_test, _m_shift_into_cmd),
    ("dw_on_odd_address", _dw_even_via_existing_test, _m_odd_dw),
    ("write_cmd_args_40", check_write_within_chunk, _m_cmd_args_40),
    ("write_chunk_not_multiple_of_stride", check_sc_chunk_is_whole_records, _m_write_chunk_not_multiple),
    ("tlm_far_register", check_tlm_read_within_max, _m_tlm_far),
    ("pmir_param_id_125", check_pmir_read_within_max, _m_pmir_id_125),
    ("sc_cap_60", check_sc_capacity_inside_block, _m_sc_cap_60),
    ("sc_base_moved", check_sc_capacity_inside_block, _m_sc_base_moved),
    ("param_renamed", _snapshot_check, _m_rename_param),
    ("param_dropped", _snapshot_check, _m_drop_param),
    ("param_ids_swapped", _snapshot_check, _m_id_swap),
    ("argc_13", check_argc_max, _m_argc_13),
    ("errno_duplicate", check_errno_codes_unique, _m_dup_errno),
    ("reason_duplicate", check_reason_codes_unique, _m_dup_reason),
    ("default_above_max", check_param_default_in_range, _m_default_above),
    ("default_below_min", check_param_default_in_range, _m_default_below),
    ("s16_param_min_minus_32768", check_no_s16_admits_minus_32768, _m_s16_min),
    ("s16_register_range_minus_32768", check_no_s16_admits_minus_32768, _m_signed_reg_with_range),
]


@pytest.mark.parametrize("mutate,check", [(m, c) for _, c, m in _CORRUPTIONS], ids=[k for k, _, _ in _CORRUPTIONS])
def test_corruption_is_caught(
    tmp_path: Path, doc: dict, check: Callable[[dict], list[str]], mutate: Callable[[dict], None]
) -> None:
    """Испорченная КОПИЯ в tmp_path: на целом файле инвариант чист, на копии — нет."""
    assert check(doc) == [], "инвариант красный уже на настоящем файле — демонстрация бессмысленна"
    broken = copy.deepcopy(doc)
    mutate(broken)
    path = tmp_path / "delta_v2_broken.yaml"
    path.write_text(yaml.safe_dump(broken, allow_unicode=True, sort_keys=False), encoding="utf-8")
    assert check(_load(path)) != []
