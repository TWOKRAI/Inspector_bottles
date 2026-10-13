"""Тесты автора (hazard) для SC_RUN симулятора v2 — T2.3, часть A.

Дополняют слепые приёмочные тесты `test_sim_v2_scenario.py` (их не трогают):
порядок SOFT-стопа на LINE_PASS, время `DELAY_MS` только из суммы `dt_s`,
отсутствие следов у NAK `E_SC_RECORD`, идемпотентность повтора `seq`,
восстановление Override на выходе по стопу. Ожидаемые значения — литералы
(protocol-spec §7, дефолты params.md), не из кода под тестом.

Дефолтная зона: r 100..600 мм, z -150..0, rz -360..360, сектор ±165°; дом
(300, -210, -40, -100); P_SPD_DEFAULT = 80 %.
"""

from __future__ import annotations

import pytest

from Services.robot_comm.core.protocol_v2 import ACT, CONSTANTS, ERR, KIND, OP, REASON, REG, REG_COUNT
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2

ACK = 1
NAK = 2
TICK_S = 0.01
ACTIVITY_SCENARIO = 4
SPD_DEFAULT_PCT = 80
STOP_SOFT = 1
STOP_HARD = 2


def mm(eng: float) -> int:
    return round(eng * 10)


def queue_cmd(core: RobotSimCoreV2, seq: int, opcode: int, *args: int) -> None:
    core.write(REG["CMD_SEQ"], [seq])
    core.write(REG["CMD_OPCODE"], [opcode])
    core.write(REG["CMD_ARGC"], [len(args)])
    if args:
        core.write(REG["CMD_ARGS"], [a & 0xFFFF for a in args])
    core.write(REG["CMD_FLAG"], [1])


def cmd(core: RobotSimCoreV2, seq: int, opcode: int, *args: int) -> dict:
    queue_cmd(core, seq, opcode, *args)
    core.tick(TICK_S)
    rvalc = core.read(REG["RES_RVALC"])[0]
    return {
        "status": core.read(REG["RES_STATUS"])[0],
        "errno": core.read(REG["RES_ERRNO"])[0],
        "rvals": core.read(REG["RES_RVALS"], REG_COUNT["RES_RVALS"])[:rvalc],
        "seq": core.read(REG["RES_SEQ"])[0],
    }


def reg(core: RobotSimCoreV2, name: str) -> int:
    return core.read(REG[name])[0]


def write_scenario(core: RobotSimCoreV2, offset: int, records: list[tuple]) -> None:
    """records: (x_mm, y_mm, z_mm, rz_deg, kind, action, aparam), §7.1 OP = KIND + 256·ACTION."""
    for i, (x, y, z, rz, kind, action, aparam) in enumerate(records):
        addr = REG["SC_BUF"] + (offset + i) * CONSTANTS["SC_STRIDE"]
        core.write(addr, [mm(x) & 0xFFFF, mm(y) & 0xFFFF, mm(z) & 0xFFFF, mm(rz) & 0xFFFF, kind + 256 * action, aparam])


def ready_core() -> RobotSimCoreV2:
    core = RobotSimCoreV2(fw_build=7)
    assert cmd(core, 1, OP["SERVO"], 1)["status"] == ACK
    return core


def tick_until(core: RobotSimCoreV2, pred, max_ticks: int = 3000) -> None:
    for _ in range(max_ticks):
        if pred():
            return
        core.tick(TICK_S)
    pytest.fail(f"условие не выполнилось за {max_ticks} тиков")


def pt(x: float, kind: int = KIND["LINE"], action: int = ACT["NONE"], aparam: int = 0) -> tuple:
    return (x, -210.0, -40.0, -100.0, kind, action, aparam)


# --------------------------------------------------------------------------- #
# SOFT внутри сценария ждёт ближайшую EXACT-точку, LINE_PASS его не обслуживает
# --------------------------------------------------------------------------- #


def test_soft_stop_waits_for_exact_point():
    core = ready_core()
    write_scenario(core, 0, [pt(400.0), pt(450.0, KIND["LINE_PASS"]), pt(500.0), pt(540.0)])
    res = cmd(core, 2, OP["SC_RUN"], 4, 5, 0, 0, 0, 0)
    assert res["status"] == ACK
    done_before = reg(core, "TLM_DONE_SEQ")

    tick_until(core, lambda: reg(core, "TLM_X") == 4000)  # приход в EXACT p1
    core.write(REG["STOP_REQ"], [STOP_SOFT])

    passed_line_pass = False
    for _ in range(3000):
        core.tick(TICK_S)
        if reg(core, "TLM_X") == 4500:
            passed_line_pass = True
            assert reg(core, "TLM_ACTIVITY") == ACTIVITY_SCENARIO, "на LINE_PASS SOFT не обслуживается"
            assert reg(core, "TLM_STOP_ACK") == 0, "STOP_ACK ждёт EXACT-точку"
        if reg(core, "TLM_ACTIVITY") == 0:
            break
    else:
        pytest.fail("сценарий не остановился")

    assert passed_line_pass, "робот должен был пройти LINE_PASS-точку 450 мм"
    assert reg(core, "TLM_X") == 5000, "SOFT срабатывает на ближайшей EXACT (500 мм), не на 450 и не на 540"
    assert reg(core, "TLM_ERRNO_LAST") == ERR["E_ABORTED"]
    assert reg(core, "TLM_ERR_SEQ") == 2
    assert reg(core, "TLM_STOP_ACK") == STOP_SOFT
    assert reg(core, "TLM_DONE_SEQ") == done_before, "стоп не даёт DONE_SEQ"
    assert reg(core, "TLM_SC_INDEX") == 3
    assert reg(core, "TLM_SC_DONE_N") == 3, "завершены записи 1..3 из 4"
    assert reg(core, "TLM_SPD_PCT") == SPD_DEFAULT_PCT


# --------------------------------------------------------------------------- #
# DELAY_MS — только сумма dt_s из tick(), не стенные часы и не число тиков
# --------------------------------------------------------------------------- #


def test_delay_ms_counts_sum_of_dt():
    core = ready_core()
    write_scenario(core, 0, [pt(420.0, action=ACT["DELAY_MS"], aparam=1000)])
    assert cmd(core, 2, OP["SC_RUN"], 1, 5, 0, 0, 0, 0)["status"] == ACK

    tick_until(core, lambda: reg(core, "TLM_X") == 4200)
    assert reg(core, "TLM_ACTIVITY") == ACTIVITY_SCENARIO, "на тике прихода пауза не завершается"
    queue_cmd(core, 99, OP["PING"])  # во время паузы mailbox не опрашивается

    core.tick(0.5)
    assert reg(core, "TLM_ACTIVITY") == ACTIVITY_SCENARIO, "0.5 с из 1.0 с"
    assert reg(core, "RES_SEQ") == 2, "PING не обслуживается во время паузы"
    core.tick(0.499)
    assert reg(core, "TLM_ACTIVITY") == ACTIVITY_SCENARIO, "0.999 с из 1.0 с"
    core.tick(0.001)
    assert reg(core, "TLM_ACTIVITY") == 0, "1.000 с — пауза закончена"
    assert reg(core, "TLM_DONE_SEQ") == 2
    core.tick(TICK_S)
    assert reg(core, "RES_SEQ") == 99, "после сценария mailbox снова опрашивается каждый тик"


# --------------------------------------------------------------------------- #
# NAK E_SC_RECORD не оставляет следов
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "offset,records,expected_rvals",
    [
        (0, [pt(440.0, action=ACT["DO_ON"], aparam=6), pt(480.0, KIND["LINE_PASS"])], [1, REASON["R_LAST_PASS"]]),
        (0, [pt(440.0, action=ACT["DO_ON"], aparam=6), pt(700.0)], [1, REASON["R_OUT_OF_ZONE"]]),
        (
            0,
            [pt(440.0, action=ACT["DO_ON"], aparam=6), (-100.0, -60.0, -40.0, -100.0, KIND["LINE"], ACT["NONE"], 0)],
            [1, REASON["R_DEAD_ZONE"]],
        ),
        (0, [pt(440.0, action=ACT["SPEED_PCT"], aparam=0)], [0, REASON["R_APARAM"]]),
        (20, [pt(440.0), pt(460.0), pt(480.0, kind=3)], [2, REASON["R_KIND"]]),
    ],
    ids=["last_line_pass", "out_of_zone", "dead_zone", "speed_pct_zero", "kind_at_offset"],
)
def test_sc_record_nak_leaves_no_trace(offset, records, expected_rvals):
    core = ready_core()
    # Предыстория: успешный сценарий, чтобы TLM_SC_*/DO/поза были ненулевыми.
    write_scenario(core, 40, [pt(420.0, action=ACT["DO_ON"], aparam=3)])
    assert cmd(core, 2, OP["SC_RUN"], 1, 10, 40, 0, 0, 0)["status"] == ACK
    tick_until(core, lambda: reg(core, "TLM_ACTIVITY") == 0)
    snapshot_names = (
        "TLM_X",
        "TLM_Y",
        "TLM_DO_MASK",
        "TLM_SC_ID",
        "TLM_SC_TOTAL",
        "TLM_SC_INDEX",
        "TLM_SC_DONE_N",
        "TLM_DONE_SEQ",
        "TLM_ERR_EVT",
        "TLM_SPD_PCT",
    )
    before = {n: reg(core, n) for n in snapshot_names}
    assert (before["TLM_X"], before["TLM_DO_MASK"], before["TLM_SC_ID"], before["TLM_SC_DONE_N"]) == (4200, 4, 10, 1)

    write_scenario(core, offset, records)
    res = cmd(core, 3, OP["SC_RUN"], len(records), 77, offset, 0, 0, 0)
    assert res["status"] == NAK
    assert res["errno"] == ERR["E_SC_RECORD"]
    assert res["rvals"] == expected_rvals
    for _ in range(5):
        core.tick(TICK_S)
    assert reg(core, "TLM_ACTIVITY") == 0
    assert {n: reg(core, n) for n in snapshot_names} == before


# --------------------------------------------------------------------------- #
# Повтор seq SC_RUN не исполняет сценарий заново
# --------------------------------------------------------------------------- #


def test_sc_run_repeat_seq_is_idempotent():
    core = ready_core()
    write_scenario(core, 0, [pt(420.0)])
    assert cmd(core, 2, OP["SC_RUN"], 1, 10, 0, 0, 0, 0)["status"] == ACK
    tick_until(core, lambda: reg(core, "TLM_ACTIVITY") == 0)
    assert reg(core, "TLM_X") == 4200

    write_scenario(core, 0, [pt(500.0)])  # буфер сменился — повтор seq всё равно не исполняется
    res = cmd(core, 2, OP["SC_RUN"], 1, 20, 0, 0, 0, 0)
    assert res["status"] == ACK
    assert res["seq"] == 2
    for _ in range(50):
        core.tick(TICK_S)
    assert reg(core, "TLM_ACTIVITY") == 0
    assert reg(core, "TLM_X") == 4200
    assert reg(core, "TLM_SC_ID") == 10
    assert reg(core, "TLM_DONE_SEQ") == 2


# --------------------------------------------------------------------------- #
# SPEED_PCT живёт до конца сценария; HARD -> Override снова P_SPD_DEFAULT
# --------------------------------------------------------------------------- #


def test_speed_pct_restored_after_hard_stop():
    core = ready_core()
    write_scenario(core, 0, [pt(400.0, action=ACT["SPEED_PCT"], aparam=50), pt(550.0, action=ACT["DO_OFF"], aparam=1)])
    assert cmd(core, 2, OP["DO_SET"], 1, 1)["status"] == ACK
    assert cmd(core, 3, OP["SC_RUN"], 2, 5, 0, 0, 0, 0)["status"] == ACK
    assert reg(core, "TLM_SPD_PCT") == SPD_DEFAULT_PCT, "первый отрезок — на P_SPD_DEFAULT"

    tick_until(core, lambda: reg(core, "TLM_X") == 4000)
    assert reg(core, "TLM_SPD_PCT") == 50, "SPEED_PCT действует со следующего отрезка, старт — в тике прихода"
    core.tick(TICK_S)
    assert reg(core, "TLM_ACTIVITY") == ACTIVITY_SCENARIO

    core.write(REG["STOP_REQ"], [STOP_HARD])
    core.tick(TICK_S)
    assert reg(core, "TLM_ACTIVITY") == 0
    assert reg(core, "TLM_ERRNO_LAST") == ERR["E_ABORTED"]
    assert reg(core, "TLM_SPD_PCT") == SPD_DEFAULT_PCT
    assert reg(core, "TLM_SC_DONE_N") == 1
    assert reg(core, "TLM_DO_MASK") == 1, "DO_OFF недостигнутой точки не исполняется, стоп DO не трогает"


# --------------------------------------------------------------------------- #
# Нормальный DONE сценария: регистр Override возвращается к P_SPD_DEFAULT
# --------------------------------------------------------------------------- #


def test_speed_pct_register_restored_after_normal_done():
    """После штатного DONE сценария со ``SPEED_PCT`` = 50 регистр ``TLM_SPD_PCT`` в IDLE равен 80.

    Вход: ``SPEED_PCT`` 50 на первой точке, две EXACT-точки, ``SC_RUN``, ход до IDLE. Вызов следующего
    хода регистр не читает (берёт ``P_SPD_DEFAULT`` напрямую), поэтому слепое место — именно регистр.
    Литерал 80 — ``P_SPD_DEFAULT`` по умолчанию (``params_v2.PARAMS[0]``, 'default': 80).

    НЕ доказывает: возврат на пути обрыва (его держит ``test_speed_pct_restored_after_hard_stop``);
    что Override обычного хода вне сценария возвращается так же — здесь только путь ``SC_RUN``."""
    core = ready_core()
    write_scenario(core, 0, [pt(400.0, action=ACT["SPEED_PCT"], aparam=50), pt(450.0)])
    assert cmd(core, 2, OP["SC_RUN"], 2, 5, 0, 0, 0, 0)["status"] == ACK

    tick_until(core, lambda: reg(core, "TLM_X") == 4000)
    assert reg(core, "TLM_SPD_PCT") == 50, "контроль: SPEED_PCT сценария действует до конца хода"

    tick_until(core, lambda: reg(core, "TLM_ACTIVITY") == 0)
    assert reg(core, "TLM_DONE_SEQ") == 2, "сценарий кончился штатно (DONE), а не обрывом"
    assert reg(core, "TLM_SPD_PCT") == SPD_DEFAULT_PCT
