"""Хазард-тесты автора для мотора симулятора v2 (T2.2, plans/robot-protocol-v2).

Дополняют независимые приёмочные тесты `test_sim_v2_motion.py` — не заменяют
их. Каждый тест ловит конкретную опасность именно ЭТОГО механизма
(интерполяция + плоскость стопа + mailbox + рестарт), а не переповторяет
приёмку. Регистр-помощники скопированы из `test_sim_v2_motion.py`, а не
импортированы (паттерн T2.1: `test_sim_v2_core.py` / `test_sim_v2_core_internal.py`).
"""

from __future__ import annotations

import pytest

from Services.robot_comm.core.params_v2 import PARAM_ID, PARAMS
from Services.robot_comm.core.protocol_v2 import KIND, OP, REG, REG_COUNT, STOP_LEVEL
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2

ACK = 1
NAK = 2
FW_BUILD = 7


def u16(value: int) -> int:
    return value & 0xFFFF


def mm(eng: float) -> int:
    return round(eng * 10)


def fresh_core(**kw) -> RobotSimCoreV2:
    return RobotSimCoreV2(fw_build=FW_BUILD, **kw)


def cmd(core, seq: int, opcode: int, *args: int) -> dict:
    core.write(REG["CMD_SEQ"], [u16(seq)])
    core.write(REG["CMD_OPCODE"], [opcode])
    core.write(REG["CMD_ARGC"], [len(args)])
    if args:
        core.write(REG["CMD_ARGS"], [u16(a) for a in args])
    core.write(REG["CMD_FLAG"], [1])
    core.tick()
    return read_res(core)


def read_res(core) -> dict:
    status = core.read(REG["RES_STATUS"], 1)[0]
    errno = core.read(REG["RES_ERRNO"], 1)[0]
    rvalc = core.read(REG["RES_RVALC"], 1)[0]
    rvals = core.read(REG["RES_RVALS"], REG_COUNT["RES_RVALS"])[:rvalc]
    seq_written = core.read(REG["RES_SEQ"], 1)[0]
    return {"status": status, "errno": errno, "rvalc": rvalc, "rvals": rvals, "seq": seq_written}


def servo_on(core, seq: int = 1) -> None:
    res = cmd(core, seq, OP["SERVO"], 1)
    assert res["status"] == ACK


def home_target() -> tuple[int, int, int, int]:
    return (
        PARAMS[PARAM_ID["P_HOME_X"]]["default"],
        PARAMS[PARAM_ID["P_HOME_Y"]]["default"],
        PARAMS[PARAM_ID["P_HOME_Z"]]["default"],
        PARAMS[PARAM_ID["P_HOME_RZ"]]["default"],
    )


def run_until_activity_zero(core, max_ticks: int = 5000) -> int:
    for i in range(max_ticks):
        if core.read(REG["TLM_ACTIVITY"], 1)[0] == 0:
            return i
        core.tick()
    pytest.fail(f"команда всё ещё активна после {max_ticks} тиков — цикл не должен зависать")


def _start_long_ptp(core, seq: int, distance_mm: float = 150.0, spd: int = 20) -> int:
    hx, hy, hz, hrz = home_target()
    tx = hx + mm(distance_mm)
    res = cmd(core, seq, OP["PTP_MOVE"], tx, hy, hz, hrz, KIND["LINE"], spd)
    assert res["status"] == ACK
    return res["seq"]


# --------------------------------------------------------------------------- #
# Плоскость стопа: SOFT pending -> HARD, SOFT pending -> SOFT
# --------------------------------------------------------------------------- #


def test_soft_pending_then_hard_produces_exactly_one_err_evt():
    # Опасность: _pending_soft и обычный abort-now делят один и тот же счётчик
    # ERR_EVT — код, забывший сбросить/не задвоить событие, дал бы 0 или 2.
    core = fresh_core()
    servo_on(core, 1)
    move_seq = _start_long_ptp(core, 2)
    core.tick()
    evt_before = core.read(REG["TLM_ERR_EVT"], 1)[0]

    core.write(REG["STOP_REQ"], [STOP_LEVEL["SOFT"]])
    core.tick()
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] != 0  # ещё pending, событие не должно расти

    core.write(REG["STOP_REQ"], [STOP_LEVEL["HARD"]])
    core.tick()

    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == 0
    assert core.read(REG["TLM_ERR_EVT"], 1)[0] == evt_before + 1
    assert core.read(REG["TLM_ERR_SEQ"], 1)[0] == move_seq
    assert core.read(REG["TLM_STOP_ACK"], 1)[0] == STOP_LEVEL["HARD"]


def test_soft_pending_then_second_soft_echoes_latest_value_no_abort_yet():
    # Опасность: если _pending_soft не перезаписывается новым значением (или
    # если второй SOFT ошибочно трактуется как HARD/HALT), ход оборвётся
    # раньше времени или эхо на прибытии будет от первого SOFT, не второго.
    core = fresh_core()
    servo_on(core, 1)
    move_seq = _start_long_ptp(core, 2)
    core.tick()

    core.write(REG["STOP_REQ"], [STOP_LEVEL["SOFT"]])  # value=1
    core.tick()
    core.write(REG["STOP_REQ"], [9])  # тоже SOFT (9%4=1), другое сырое значение
    core.tick()
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] != 0, "второй SOFT тоже pending"
    assert core.read(REG["TLM_STOP_ACK"], 1)[0] == 0, "эхо ещё не должно быть записано"

    run_until_activity_zero(core)
    assert core.read(REG["TLM_STOP_ACK"], 1)[0] == 9, "эхо должно быть последним pending-значением (9), не 1"
    assert core.read(REG["TLM_ERR_SEQ"], 1)[0] == move_seq


# --------------------------------------------------------------------------- #
# Mailbox: повтор seq во время движения не перезапускает ход
# --------------------------------------------------------------------------- #


def test_repeat_seq_during_motion_does_not_restart_move():
    # Опасность: если _handle_mailbox не ловит повтор seq и снова вызывает
    # _op_ptp_move, self._active пересоздастся с pos=текущая (уже сдвинутая)
    # поза -> ход "прыгнет" вперёд или собьётся счёт тиков.
    core = fresh_core()
    servo_on(core, 1)
    hx, hy, hz, hrz = home_target()
    tx = hx + mm(150.0)
    res = cmd(core, 2, OP["PTP_MOVE"], tx, hy, hz, hrz, KIND["LINE"], 10)
    assert res["status"] == ACK
    core.tick()
    core.tick()
    x_before = core.read(REG["TLM_X"], 1)[0]

    # Повтор того же CMD_SEQ=2 (mailbox не должен исполнить его заново).
    core.write(REG["CMD_SEQ"], [u16(2)])
    core.write(REG["CMD_OPCODE"], [OP["PTP_MOVE"]])
    core.write(REG["CMD_ARGC"], [6])
    core.write(REG["CMD_ARGS"], [u16(tx), u16(hy), u16(hz), u16(hrz), KIND["LINE"], 10])
    core.write(REG["CMD_FLAG"], [1])
    core.tick()
    x_after = core.read(REG["TLM_X"], 1)[0]

    # Один тик низкоскоростного хода (10%) не долетает до цели -> движение
    # продолжилось штатно на один шаг, а не перезапустилось с текущей позы.
    assert x_after != x_before, "тик должен был продвинуть позу"
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] != 0


# --------------------------------------------------------------------------- #
# PARAM_SET live во время хода не ломает интерполяцию
# --------------------------------------------------------------------------- #


def test_param_set_live_during_move_does_not_break_motion():
    # Опасность: активная команда хранит "speed" копией на старте; если
    # PARAM_SET P_SPD_L (apply=live... нет, но P_JOG_LEASE_MS live) вместо
    # этого код читал self._values заново на каждом тике, поведение стало бы
    # неопределённым посреди хода. Проверяем на P_TLM_EVERY (apply=live,
    # не участвует в движении вовсе) — ход обязан доехать штатно.
    core = fresh_core()
    servo_on(core, 1)
    move_seq = _start_long_ptp(core, 2, distance_mm=100.0, spd=100)
    core.tick()

    res = cmd(core, 3, OP["PARAM_SET"], PARAM_ID["P_TLM_EVERY"], 7)
    assert res["status"] == ACK, "P_TLM_EVERY (apply=live) обязан приниматься во время хода"

    run_until_activity_zero(core, max_ticks=200)
    hx, hy, hz, hrz = home_target()
    assert core.read(REG["TLM_X"], 1)[0] == hx + mm(100.0)
    assert core.read(REG["TLM_DONE_SEQ"], 1)[0] == move_seq


# --------------------------------------------------------------------------- #
# JOG_CONT: без потери округления на малой скорости
# --------------------------------------------------------------------------- #


def test_jog_cont_1mm_per_s_at_default_dt_moves_without_rounding_loss():
    # Опасность: если внутренняя поза jog хранится как int/округлённый регистр
    # вместо float, 1мм/с * 0.01с = 0.01мм/тик округлится в 0 каждый тик, и
    # поза не сдвинется вовсе за 10 тиков (round(0.01*10)=0 при целочисленном
    # накоплении). Contract явно требует float-позу без потери округления.
    core = fresh_core()
    servo_on(core, 1)
    # (300.0, 0.0, -75.0, 0.0): r=300 в [100,600], z=-75 в [-150,0] — в зоне с запасом.
    move_target = (mm(300.0), mm(0.0), mm(-75.0), mm(0.0))
    res = cmd(core, 2, OP["PTP_MOVE"], *move_target, KIND["JOINT"], 100)
    assert res["status"] == ACK
    run_until_activity_zero(core)

    res = cmd(core, 3, OP["JOG_CONT"], 1, 1)  # X+, 1 мм/с
    assert res["status"] == ACK
    x0 = core.read(REG["TLM_X"], 1)[0]
    for i in range(10):
        core.write(REG["JOG_LEASE"], [i + 1])
        core.tick(0.01)
    x_after = core.read(REG["TLM_X"], 1)[0]
    # 10 тиков * 1мм/с * 0.01с = 0.1мм -> raw +1 (×0.1мм на единицу регистра).
    assert x_after == x0 + 1, f"10 тиков по 1мм/с должны дать 0.1мм (raw +1), получено delta={x_after - x0}"


# --------------------------------------------------------------------------- #
# Большой dt: MAX_STEP_MM обязан требовать >=3 тика даже при explicit большом dt
# --------------------------------------------------------------------------- #


def test_huge_dt_still_needs_at_least_3_ticks_for_100mm():
    # Опасность: если MAX_STEP_MM не применяется (или применяется только к
    # tick() без аргумента), один core.tick(1.0) при v=1500мм/с домчал бы
    # 100мм ЗА ОДИН тик после ACK — нарушая инвариант "минимум 3 тика".
    core = fresh_core()
    servo_on(core, 1)
    hx, hy, hz, hrz = home_target()
    tx = hx + mm(100.0)
    res = cmd(core, 2, OP["PTP_MOVE"], tx, hy, hz, hrz, KIND["LINE"], 100)
    assert res["status"] == ACK
    ticks = 1  # ACK-тик уже сделал первый шаг
    while core.read(REG["TLM_ACTIVITY"], 1)[0] != 0 and ticks < 10:
        core.tick(1.0)  # огромный dt явным аргументом
        ticks += 1
    assert ticks >= 3, f"100мм-ход обязан занять минимум 3 тика даже при dt=1.0с, получено {ticks}"
    assert core.read(REG["TLM_X"], 1)[0] == tx


# --------------------------------------------------------------------------- #
# Рестарт посреди JOG_CONT: MOVING/ACTIVITY не должны застрять в "едет"
# --------------------------------------------------------------------------- #


def test_restart_mid_jog_leaves_moving_and_activity_zero():
    # Опасность: _boot() явно обнуляет MOVING/ACTIVITY при рестарте (правило
    # из T2.1-ревью для PTP-заглушки) — тест доказывает, что это верно и для
    # JOG_CONT (новый T2.2 тип активной команды), а не только для "move".
    core = fresh_core()
    servo_on(core, 1)
    res = cmd(core, 2, OP["JOG_CONT"], 1, 10)
    assert res["status"] == ACK
    core.tick()
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] != 0
    assert core.read(REG["TLM_MOVING"], 1)[0] == 1

    restarted = RobotSimCoreV2(regs=core.regs, fw_build=FW_BUILD)
    assert restarted.read(REG["TLM_ACTIVITY"], 1)[0] == 0
    assert restarted.read(REG["TLM_MOVING"], 1)[0] == 0
    # Тик после рестарта не должен ожить и снова начать двигаться сам по себе.
    x_before = restarted.read(REG["TLM_X"], 1)[0]
    restarted.tick()
    assert restarted.read(REG["TLM_X"], 1)[0] == x_before
    assert restarted.read(REG["TLM_ACTIVITY"], 1)[0] == 0
