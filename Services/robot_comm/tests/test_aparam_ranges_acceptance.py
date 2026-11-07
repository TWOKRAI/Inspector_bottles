"""Слепые приёмочные тесты T1.4: диапазоны аргумента действия сценария (``scenario.aparam``).

Написаны ДО реализации из текста приёмки, без чтения реализации. Контракт:

- ``delta_v2.yaml`` получает ключ ``scenario.aparam``: действие -> ``{min, max}`` или ``{param: P_*}``
  (у ACCEL — ``{param: P_ACC_L}``);
- ``codegen.generate(root)`` кладёт в текст ``core/protocol_v2.py`` словарь ``ACT_RANGE``
  (имя действия -> ``(lo, hi)`` включительно, без NONE), ``codegen.lua_block(root)`` — таблицу ``ARNG``
  (ключ — код действия, значение ``{lo = .., hi = ..}``);
- потребители читают ``protocol_v2.ACT_RANGE`` в момент проверки: ``programs.Action``, sim v2 (запись
  сценария, ``SC_RUN`` — стартовое состояние, ``DO_SET``).

Ожидаемые значения — литералы из приёмки. Подмена диапазона — ``monkeypatch.setitem`` по словарю
``protocol_v2.ACT_RANGE`` БЕЗ ``raising=False``: пока словаря нет, тест падает на ``AttributeError``.
Ветки skip нет: для Lua при наличии ``lupa`` дополнительно исполняется блок, текстовая проверка идёт всегда.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from Services.robot_comm import codegen
from Services.robot_comm.core import protocol_v2
from Services.robot_comm.core.protocol_v2 import ACT, CONSTANTS, ERR, KIND, OP, REASON, REG, REG_COUNT
from Services.robot_comm.programs import Action
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2

ACK = 1
NAK = 2
FW_BUILD = 7

_YAML_REL = Path("Services/robot_comm/protocols/delta_v2.yaml")
# tests -> robot_comm -> Services -> корень worktree
_ROOT = Path(__file__).resolve().parents[3]

# Литерал из приёмки (A1): настоящий YAML.
_EXPECTED_REAL = {
    "DO_ON": (1, 16),
    "DO_OFF": (1, 16),
    "DELAY_MS": (0, 65535),
    "SPEED_PCT": (1, 100),
    "ACCEL": (100, 50000),
    "ACCUR": (0, 1),
}


# --------------------------------------------------------------------------- #
# Хелперы
# --------------------------------------------------------------------------- #


def _generated_act_range(root: Path) -> dict:
    """``ACT_RANGE`` из сгенерированного текста ``core/protocol_v2.py`` (модуль без импортов)."""
    texts = codegen.generate(root)
    protocol_texts = [t for p, t in texts.items() if Path(p).as_posix().endswith("core/protocol_v2.py")]
    assert len(protocol_texts) == 1, (
        f"generate(root) обязан вернуть ровно один текст core/protocol_v2.py: {list(texts)}"
    )
    namespace: dict = {}
    exec(protocol_texts[0], namespace)  # noqa: S102 — сгенерированный модуль без импортов, см. приёмку
    return namespace["ACT_RANGE"]


def _copy_yaml(dst_root: Path) -> Path:
    """Копия настоящего YAML в ``dst_root`` по тому же относительному пути. Возвращает путь копии."""
    dst = dst_root / _YAML_REL
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(_ROOT / _YAML_REL, dst)
    return dst


def _arng_body(block: str) -> str:
    """Тело таблицы ``ARNG`` из Lua-блока (разбор скобок). Нет ``ARNG`` -> AssertionError."""
    match = re.search(r"\bARNG\s*=\s*\{", block)
    assert match is not None, "в Lua-блоке нет таблицы ARNG"
    depth = 0
    for pos in range(match.end() - 1, len(block)):
        char = block[pos]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return block[match.end() : pos]
    raise AssertionError("таблица ARNG в Lua-блоке не закрыта фигурной скобкой")


def _arng_has_entry(body: str, code: int, lo: int | None, hi: int | None) -> bool:
    """Есть ли в теле ARNG запись ``[code] = { lo = .., hi = .. }`` (whitespace-терпимо, lo/hi None — любые)."""
    lo_re = r"\d+" if lo is None else str(lo)
    hi_re = r"\d+" if hi is None else str(hi)
    pattern = rf"\[\s*{code}\s*\]\s*=\s*\{{\s*lo\s*=\s*{lo_re}\s*,\s*hi\s*=\s*{hi_re}\s*,?\s*\}}"
    return re.search(pattern, body) is not None


def mm(eng: float) -> int:
    return round(eng * 10)


def read_res(core) -> dict:
    status = core.read(REG["RES_STATUS"], 1)[0]
    errno = core.read(REG["RES_ERRNO"], 1)[0]
    rvalc = core.read(REG["RES_RVALC"], 1)[0]
    rvals = core.read(REG["RES_RVALS"], REG_COUNT["RES_RVALS"])[:rvalc]
    return {"status": status, "errno": errno, "rvalc": rvalc, "rvals": rvals}


def cmd(core, seq: int, opcode: int, *args: int) -> dict:
    core.write(REG["CMD_SEQ"], [seq])
    core.write(REG["CMD_OPCODE"], [opcode])
    core.write(REG["CMD_ARGC"], [len(args)])
    if args:
        core.write(REG["CMD_ARGS"], [a & 0xFFFF for a in args])
    core.write(REG["CMD_FLAG"], [1])
    core.tick()
    return read_res(core)


def servo_core() -> RobotSimCoreV2:
    core = RobotSimCoreV2(fw_build=FW_BUILD)
    res = cmd(core, 1, OP["SERVO"], 1)
    assert res["status"] == ACK, "предусловие: серво включается"
    return core


def write_scenario(core, records: list[tuple]) -> None:
    """records: (x_mm, y_mm, z_mm, rz_mm, kind, action, aparam); stride 6, OP = KIND + 256 * ACTION."""
    for i, (x, y, z, rz, kind, action, aparam) in enumerate(records):
        op = kind + 256 * action
        addr = REG["SC_BUF"] + i * CONSTANTS["SC_STRIDE"]
        core.write(addr, [mm(x), mm(y), mm(z), mm(rz), op, aparam])


def _point(action: int, aparam: int) -> tuple:
    return (420.0, -210.0, -40.0, -100.0, KIND["LINE"], action, aparam)


_GOOD_POINT = _point(ACT["NONE"], 0)


def _sc_run(core, *, count: int, spd_pct: int = 0, accel: int = 0, accur: int = 0) -> dict:
    return cmd(core, 2, OP["SC_RUN"], count, 1, 0, spd_pct, accel, accur)


# =========================================================================== #
# A1. Настоящий YAML
# =========================================================================== #


def test_a1_generated_act_range_real_yaml():
    assert _generated_act_range(_ROOT) == _EXPECTED_REAL


def test_a1_committed_protocol_module_has_same_act_range():
    # Сгенерированный и закоммиченный core/protocol_v2.py обязаны совпадать (на диске после codegen).
    assert protocol_v2.ACT_RANGE == _EXPECTED_REAL


# =========================================================================== #
# A2. Копия YAML с изменёнными границами -> generate видит их
# =========================================================================== #


def test_a2_tmp_yaml_overrides_reach_act_range(tmp_path):
    yaml_path = _copy_yaml(tmp_path)
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    aparam = data["scenario"].get("aparam")
    assert aparam is not None, "в delta_v2.yaml нет ключа scenario.aparam"
    aparam["SPEED_PCT"]["max"] = 50
    data["params"]["P_ACC_L"]["min"] = 200
    data["params"]["P_ACC_L"]["max"] = 40000
    yaml_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    got = _generated_act_range(tmp_path)

    assert got["SPEED_PCT"] == (1, 50)
    assert got["ACCEL"] == (200, 40000)
    assert {k: v for k, v in got.items() if k not in ("SPEED_PCT", "ACCEL")} == {
        "DO_ON": (1, 16),
        "DO_OFF": (1, 16),
        "DELAY_MS": (0, 65535),
        "ACCUR": (0, 1),
    }


# =========================================================================== #
# A3. programs.Action читает ACT_RANGE в момент проверки
# =========================================================================== #


def test_a3_action_above_patched_max_rejected(monkeypatch):
    monkeypatch.setitem(protocol_v2.ACT_RANGE, "SPEED_PCT", (1, 50))
    with pytest.raises(ValidationError):
        Action(act="SPEED_PCT", value=51)


def test_a3_action_at_patched_max_accepted(monkeypatch):
    monkeypatch.setitem(protocol_v2.ACT_RANGE, "SPEED_PCT", (1, 50))
    assert Action(act="SPEED_PCT", value=50).value == 50


def test_a3_action_patch_is_per_action_do_on(monkeypatch):
    monkeypatch.setitem(protocol_v2.ACT_RANGE, "DO_ON", (1, 8))
    with pytest.raises(ValidationError):
        Action(act="DO_ON", value=9)
    assert Action(act="DO_ON", value=8).value == 8


# =========================================================================== #
# A4. sim v2 читает ACT_RANGE
# =========================================================================== #


def test_a4_sim_record_above_patched_max_nak_e_sc_record(monkeypatch):
    monkeypatch.setitem(protocol_v2.ACT_RANGE, "SPEED_PCT", (1, 50))
    core = servo_core()
    write_scenario(core, [_GOOD_POINT, _point(ACT["SPEED_PCT"], 51)])

    res = _sc_run(core, count=2)

    assert res["status"] == NAK
    assert res["errno"] == ERR["E_SC_RECORD"]
    assert res["rvalc"] == 2
    assert res["rvals"][0] == 1, "индекс плохой записи"
    assert res["rvals"][1] == REASON["R_APARAM"]


def test_a4_sim_record_at_patched_max_ack(monkeypatch):
    monkeypatch.setitem(protocol_v2.ACT_RANGE, "SPEED_PCT", (1, 50))
    core = servo_core()
    write_scenario(core, [_GOOD_POINT, _point(ACT["SPEED_PCT"], 50)])

    res = _sc_run(core, count=2)

    assert res["status"] == ACK


def test_a4_sc_run_start_spd_pct_above_patched_max_nak_e_range(monkeypatch):
    monkeypatch.setitem(protocol_v2.ACT_RANGE, "SPEED_PCT", (1, 50))
    core = servo_core()
    write_scenario(core, [_GOOD_POINT])

    res = _sc_run(core, count=1, spd_pct=51)

    assert res["status"] == NAK
    assert res["errno"] == ERR["E_RANGE"]
    assert res["rvalc"] >= 1
    assert res["rvals"][0] == REASON["R_APARAM"]


def test_a4_sc_run_start_spd_pct_at_patched_max_ack(monkeypatch):
    monkeypatch.setitem(protocol_v2.ACT_RANGE, "SPEED_PCT", (1, 50))
    core = servo_core()
    write_scenario(core, [_GOOD_POINT])

    res = _sc_run(core, count=1, spd_pct=50)

    assert res["status"] == ACK


def test_a4_do_set_channel_above_patched_do_on_max_nak_e_range(monkeypatch):
    monkeypatch.setitem(protocol_v2.ACT_RANGE, "DO_ON", (1, 8))
    core = servo_core()

    res = cmd(core, 2, OP["DO_SET"], 9, 1)

    assert res["status"] == NAK
    assert res["errno"] == ERR["E_RANGE"]


def test_a4_do_set_channel_at_patched_do_on_max_ack(monkeypatch):
    monkeypatch.setitem(protocol_v2.ACT_RANGE, "DO_ON", (1, 8))
    core = servo_core()

    res = cmd(core, 2, OP["DO_SET"], 8, 1)

    assert res["status"] == ACK


# =========================================================================== #
# A4b. SC_RUN: стартовые accur и accel
# =========================================================================== #


def test_a4b_sc_run_accur_above_patched_range_nak_e_range(monkeypatch):
    # accur на проводе = значение ACCUR + 1: accur=2 -> 1, вне (0, 0)
    monkeypatch.setitem(protocol_v2.ACT_RANGE, "ACCUR", (0, 0))
    core = servo_core()
    write_scenario(core, [_GOOD_POINT])

    res = _sc_run(core, count=1, accur=2)

    assert res["status"] == NAK
    assert res["errno"] == ERR["E_RANGE"]
    assert res["rvalc"] >= 1
    assert res["rvals"][0] == REASON["R_APARAM"]


def test_a4b_sc_run_accur_in_patched_range_not_nak(monkeypatch):
    # accur=1 -> значение 0, внутри (0, 0)
    monkeypatch.setitem(protocol_v2.ACT_RANGE, "ACCUR", (0, 0))
    core = servo_core()
    write_scenario(core, [_GOOD_POINT])

    res = _sc_run(core, count=1, accur=1)

    assert res["status"] != NAK, f"accur=1 в диапазоне, ответ {res}"


def test_a4b_sc_run_accur_zero_means_unset_not_nak(monkeypatch):
    monkeypatch.setitem(protocol_v2.ACT_RANGE, "ACCUR", (0, 0))
    core = servo_core()
    write_scenario(core, [_GOOD_POINT])

    res = _sc_run(core, count=1, accur=0)

    assert res["status"] != NAK, f"accur=0 — «не задано», ответ {res}"


def test_a4b_sc_run_accel_above_patched_max_nak_e_range(monkeypatch):
    monkeypatch.setitem(protocol_v2.ACT_RANGE, "ACCEL", (100, 200))
    core = servo_core()
    write_scenario(core, [_GOOD_POINT])

    res = _sc_run(core, count=1, accel=201)

    assert res["status"] == NAK
    assert res["errno"] == ERR["E_RANGE"]


def test_a4b_sc_run_accel_at_patched_max_not_nak(monkeypatch):
    monkeypatch.setitem(protocol_v2.ACT_RANGE, "ACCEL", (100, 200))
    core = servo_core()
    write_scenario(core, [_GOOD_POINT])

    res = _sc_run(core, count=1, accel=200)

    assert res["status"] != NAK, f"accel=200 в диапазоне, ответ {res}"


# =========================================================================== #
# A5. Lua-блок: таблица ARNG
# =========================================================================== #


def test_a5_lua_block_arng_text():
    block = codegen.lua_block(_ROOT)
    body = _arng_body(block)
    assert _arng_has_entry(body, 1, 1, 16), "ARNG[1] (DO_ON) = {lo = 1, hi = 16}"
    assert _arng_has_entry(body, 4, 1, 100), "ARNG[4] (SPEED_PCT) = {lo = 1, hi = 100}"
    assert _arng_has_entry(body, 5, 100, 50000), "ARNG[5] (ACCEL) = {lo = 100, hi = 50000}"


def test_a5_lua_block_arng_values_when_lupa_available():
    block = codegen.lua_block(_ROOT)
    assert re.search(r"\bARNG\b", block), "в Lua-блоке нет ARNG"
    try:
        from lupa import LuaRuntime
    except ImportError:
        # lupa нет: значения ARNG проверяет test_a5_lua_block_arng_text (текстовая ветка), здесь ветка if/else без skip.
        return
    arng = LuaRuntime().execute(block + "\nreturn ARNG")
    assert arng is not None, "ARNG не определена после исполнения блока"
    assert arng[4]["hi"] == 100
    assert arng[5]["lo"] == 100
    assert arng[1]["hi"] == 16
