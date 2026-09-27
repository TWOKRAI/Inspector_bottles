"""Авторские hazard-тесты T2.J (`sim_core_v2.py`, `plans/robot-protocol-v2/tasks.md`).

Дополняют независимые тесты тестера (`test_sim_v2_joint_path.py`) — внутренние
опасности МЕХАНИЗМА суставной интерполяции, которые видит автор, не приёмка:

  - HARD-стоп посреди JOINT замирает на FK-точке суставного пути (не на хорде),
    следующий JOINT стартует именно с неё (contract §"Stop plane" + T2.J).
  - Отложенный SOFT посреди JOINT всё равно доезжает до цели по суставам, потом
    E_ABORTED (contract §"Stop plane" не меняется T2.J).
  - Модель, чей `fk` возвращает `None` ПОСРЕДИ пути (суставы из lerp двух
    достижимых концов сами недостижимы), всё равно доезжает до цели ровно —
    финальный тик не зовёт `fk` вовсе (T2.J design).
  - Рестарт `RobotSimCoreV2(regs=old.regs)` посреди JOINT не оставляет
    полупостроенный `_active` (j_start/j_end/path_len/travelled) — `_boot()`
    сбрасывает `_active` целиком, как и до T2.J.

Регистр-помощники скопированы по паттерну `test_sim_v2_joint_path.py`/
`test_sim_v2_motion.py` (копия, не импорт — конвенция этого набора тестов).
"""

from __future__ import annotations

import math

import pytest

from Services.robot_comm.core.params_v2 import PARAM_ID, PARAMS
from Services.robot_comm.core.protocol_v2 import ERR, KIND, OP, REG, STOP_LEVEL
from Services.robot_comm.kinematics import ScaraModel
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2

ACK = 1
NAK = 2
FW_BUILD = 7
TICK_S = 0.01


def u16(value: int) -> int:
    return value & 0xFFFF


def s16(raw: int) -> int:
    return raw - 65536 if raw >= 0x8000 else raw


def mm(eng: float) -> int:
    return round(eng * 10)


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
    return {
        "status": core.read(REG["RES_STATUS"], 1)[0],
        "errno": core.read(REG["RES_ERRNO"], 1)[0],
        "seq": core.read(REG["RES_SEQ"], 1)[0],
    }


def fresh_core(**kw) -> RobotSimCoreV2:
    return RobotSimCoreV2(fw_build=FW_BUILD, **kw)


def servo_on(core, seq: int = 1) -> None:
    res = cmd(core, seq, OP["SERVO"], 1)
    assert res["status"] == ACK, "предусловие: серво должно включаться"


def run_until_activity_zero(core, max_ticks: int = 5000) -> int:
    for i in range(max_ticks):
        if core.read(REG["TLM_ACTIVITY"], 1)[0] == 0:
            return i
        core.tick()
    pytest.fail(f"команда всё ещё активна после {max_ticks} тиков — цикл не должен зависать")


def pose_eng(core) -> tuple[float, float, float, float]:
    return (
        s16(core.regs[REG["TLM_X"]]) / 10.0,
        s16(core.regs[REG["TLM_Y"]]) / 10.0,
        s16(core.regs[REG["TLM_Z"]]) / 10.0,
        s16(core.regs[REG["TLM_RZ"]]) / 10.0,
    )


def move_to_via_joint(core, seq: int, x: int, y: int, z: int, rz: int, spd: int = 100) -> dict:
    res = cmd(core, seq, OP["PTP_MOVE"], x, y, z, rz, KIND["JOINT"], spd)
    assert res["status"] == ACK, f"предусловие: JOINT в ({x},{y},{z},{rz}) должен приниматься: {res}"
    run_until_activity_zero(core)
    return res


def chord_perp_dist_xy(x0: float, y0: float, x1: float, y1: float, x: float, y: float) -> float:
    dx, dy = x1 - x0, y1 - y0
    len2 = dx * dx + dy * dy
    if len2 == 0.0:
        return math.hypot(x - x0, y - y0)
    t = ((x - x0) * dx + (y - y0) * dy) / len2
    px, py = x0 + t * dx, y0 + t * dy
    return math.hypot(x - px, y - py)


# Тот же сценарий пересечения сектора, что у тестера (боевые дефолты).
CROSS_START = (-250.0, 350.0, -75.0, 0.0)
CROSS_TARGET = (-450.0, -150.0, -75.0, 0.0)


# =========================================================================== #
# HARD-стоп посреди JOINT — замирает на FK-точке, не на хорде
# =========================================================================== #


def test_hard_stop_mid_joint_freezes_at_fk_point_not_chord():
    core = fresh_core()
    servo_on(core, 1)
    move_to_via_joint(core, 2, mm(CROSS_START[0]), mm(CROSS_START[1]), mm(CROSS_START[2]), mm(CROSS_START[3]))

    res = cmd(
        core,
        3,
        OP["PTP_MOVE"],
        mm(CROSS_TARGET[0]),
        mm(CROSS_TARGET[1]),
        mm(CROSS_TARGET[2]),
        mm(CROSS_TARGET[3]),
        KIND["JOINT"],
        100,
    )
    assert res["status"] == ACK, res
    core.tick(TICK_S)
    core.tick(TICK_S)
    core.tick(TICK_S)
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] != 0, "предусловие: ход ещё не завершился"
    frozen_before = pose_eng(core)

    core.write(REG["STOP_REQ"], [STOP_LEVEL["HARD"]])
    core.tick(TICK_S)

    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == 0, "HARD обязан прервать немедленно"
    assert core.read(REG["TLM_MOVING"], 1)[0] == 0
    frozen = pose_eng(core)
    assert frozen == frozen_before, "HARD не должен сдвигать позу — обрыв на тике обработки, замирание"
    assert core.read(REG["TLM_ERRNO_LAST"], 1)[0] == ERR["E_ABORTED"]
    assert core.read(REG["TLM_ERR_SEQ"], 1)[0] == 3
    assert core.read(REG["TLM_STOP_ACK"], 1)[0] == STOP_LEVEL["HARD"]

    # Не на хорде: суставный путь отклоняется от прямой CROSS_START->CROSS_TARGET
    # заметно (>5мм) — если бы HARD заморозил Cartesian-шаг, отклонение было бы ~0.
    dev = chord_perp_dist_xy(CROSS_START[0], CROSS_START[1], CROSS_TARGET[0], CROSS_TARGET[1], frozen[0], frozen[1])
    assert dev > 5.0, f"замёрзшая поза обязана лежать на суставном пути (не на хорде), отклонение {dev:.2f}мм"

    # Следующий JOINT стартует ИМЕННО с замёрзшей позы (не со старой CROSS_START,
    # не с цели прерванного хода) — _start_move читает _read_pose_eng() заново.
    tx, ty, tz, trz = mm(frozen[0] + 10.0), mm(frozen[1]), mm(frozen[2]), mm(frozen[3])
    res2 = cmd(core, 4, OP["PTP_MOVE"], tx, ty, tz, trz, KIND["JOINT"], 100)
    assert res2["status"] == ACK, res2
    core.tick(TICK_S)
    first_step = pose_eng(core)
    step_dist = math.hypot(first_step[0] - frozen[0], first_step[1] - frozen[1])
    assert step_dist <= 100 / 3 + 0.2, (
        f"первый шаг нового JOINT обязан стартовать от замёрзшей позы {frozen}, а не от старой "
        f"CROSS_START {CROSS_START} — получено {first_step}, шаг {step_dist:.2f}мм"
    )


# =========================================================================== #
# Отложенный SOFT посреди JOINT — доезжает по суставам до цели, потом E_ABORTED
# =========================================================================== #


def test_pending_soft_mid_joint_finishes_at_target_then_aborted():
    core = fresh_core()
    servo_on(core, 1)
    move_to_via_joint(core, 2, mm(CROSS_START[0]), mm(CROSS_START[1]), mm(CROSS_START[2]), mm(CROSS_START[3]))

    res = cmd(
        core,
        3,
        OP["PTP_MOVE"],
        mm(CROSS_TARGET[0]),
        mm(CROSS_TARGET[1]),
        mm(CROSS_TARGET[2]),
        mm(CROSS_TARGET[3]),
        KIND["JOINT"],
        100,
    )
    assert res["status"] == ACK, res
    core.tick(TICK_S)
    core.tick(TICK_S)
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] != 0

    core.write(REG["STOP_REQ"], [STOP_LEVEL["SOFT"]])
    core.tick(TICK_S)
    # pending: ход продолжается, STOP_ACK ещё не записан (contract §"Stop plane").
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] != 0, "SOFT посреди JOINT не должен прерывать сразу"
    assert core.read(REG["TLM_STOP_ACK"], 1)[0] == 0

    run_until_activity_zero(core)
    assert pose_eng(core) == pytest.approx(CROSS_TARGET, abs=0.1), "SOFT обязан доехать по суставам ДО цели"
    # TLM_DONE_SEQ=2 остался от предыдущего ШТАТНОГО хода (move_to_via_joint) —
    # обрыв SOFT НЕ пишет DONE_SEQ для seq=3, это и проверяется (!= 3, не == 0).
    assert core.read(REG["TLM_DONE_SEQ"], 1)[0] != 3, "не штатное завершение — обрыв отложенным SOFT, а не DONE"
    assert core.read(REG["TLM_ERRNO_LAST"], 1)[0] == ERR["E_ABORTED"]
    assert core.read(REG["TLM_ERR_SEQ"], 1)[0] == 3
    assert core.read(REG["TLM_STOP_ACK"], 1)[0] == STOP_LEVEL["SOFT"]
    # JOINT физически довёл руку до P_HAND даже при отложенном обрыве (docstring _progress_move).
    assert core.read(REG["TLM_HAND"], 1)[0] == PARAMS[PARAM_ID["P_HAND"]]["default"]


# =========================================================================== #
# fk() -> None посреди пути — ход всё равно доезжает до цели ровно
# =========================================================================== #


class _FkFlakyModel:
    """Делегирует всё в реальную ScaraModel, кроме `fk` — всегда `None`.

    Симулирует модель, где суставы из lerp двух ДОСТИЖИМЫХ концов сами не
    имеют прямого решения (T2.J design: фолбэк на декартов шаг для тика, но
    финальный тик не зовёт `fk` вовсе — цель достижима всегда).
    """

    def __init__(self) -> None:
        self._real = ScaraModel()
        self.kind = self._real.kind
        self.axes = self._real.axes
        self.joint_names = self._real.joint_names

    def fk(self, joints):
        return None

    def ik(self, pose, hand):
        return self._real.ik(pose, hand)

    def chain_points(self, joints):
        return self._real.chain_points(joints)

    def check_point(self, ws, pose):
        return self._real.check_point(ws, pose)

    def check_segment(self, ws, p0, p1):
        return self._real.check_segment(ws, p0, p1)


def test_fk_none_mid_path_still_reaches_target():
    core = RobotSimCoreV2(model=_FkFlakyModel())
    servo_on(core, 1)
    hx, hy, hz, hrz = (
        PARAMS[PARAM_ID["P_HOME_X"]]["default"],
        PARAMS[PARAM_ID["P_HOME_Y"]]["default"],
        PARAMS[PARAM_ID["P_HOME_Z"]]["default"],
        PARAMS[PARAM_ID["P_HOME_RZ"]]["default"],
    )
    tx, ty, tz, trz = hx + 1500, hy, hz, hrz  # +150мм по X, в зоне

    res = cmd(core, 2, OP["PTP_MOVE"], tx, ty, tz, trz, KIND["JOINT"], 100)
    assert res["status"] == ACK, res
    ticks = run_until_activity_zero(core, max_ticks=500)
    assert ticks > 0, "ход с fk()->None не должен завершаться мгновенно (иначе тест ничего не проверяет)"

    assert s16(core.read(REG["TLM_X"], 1)[0]) == tx
    assert s16(core.read(REG["TLM_Y"], 1)[0]) == ty
    assert s16(core.read(REG["TLM_Z"], 1)[0]) == tz
    assert s16(core.read(REG["TLM_RZ"], 1)[0]) == trz
    assert core.read(REG["TLM_DONE_SEQ"], 1)[0] == 2


# =========================================================================== #
# Рестарт посреди JOINT — не оставляет полупостроенный _active
# =========================================================================== #


def test_restart_mid_joint_leaves_no_half_built_active_move():
    core = fresh_core()
    servo_on(core, 1)
    res = cmd(
        core,
        2,
        OP["PTP_MOVE"],
        mm(CROSS_TARGET[0]),
        mm(CROSS_TARGET[1]),
        mm(CROSS_TARGET[2]),
        mm(CROSS_TARGET[3]),
        KIND["JOINT"],
        100,
    )
    assert res["status"] == ACK, res
    core.tick(TICK_S)
    core.tick(TICK_S)
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] != 0, "предусловие: ход ещё активен (j_start/j_end/travelled заведены)"
    assert core._active is not None and core._active.get("j_start") is not None

    restarted = RobotSimCoreV2(regs=core.regs, fw_build=FW_BUILD)

    assert restarted._active is None, "рестарт не должен унаследовать активный ход из старого core"
    assert restarted.regs[REG["TLM_MOVING"]] == 0
    assert restarted.regs[REG["TLM_ACTIVITY"]] == 0
    # Свежий core после рестарта принимает новую команду без падения на "полупостроенном" _active.
    res2 = cmd(restarted, 3, OP["SERVO"], 1)
    assert res2["status"] == ACK, res2


def test_hand_flip_passes_stretched_arm():
    """Смена руки посреди JOINT физически проводит руку через вытянутое положение (J2 = 0, r = l1 + l2).

    Инъекция ведущего: конец пути решался с рукой TLM_HAND вместо P_HAND — поза цели та же, все тесты
    оставались зелёными, а путь руки (и её вид в окне) — без перекладки. Этот тест держит путь, не только цель.
    """
    from Services.robot_comm.tests.test_sim_v2_joint_path import (
        cmd,
        fresh_core,
        home_target,
        servo_on,
        track_pose_until_done,
        u16,
    )

    core = fresh_core()
    servo_on(core, 1)
    new_hand = 1 - PARAMS[PARAM_ID["P_HAND"]]["default"]
    assert cmd(core, 2, OP["PARAM_SET"], PARAM_ID["P_HAND"], u16(new_hand))["status"] == ACK
    hx, hy, hz, hrz = home_target()
    assert cmd(core, 3, OP["PTP_MOVE"], hx + 500, hy, hz, hrz, KIND["JOINT"], 100)["status"] == ACK
    samples = track_pose_until_done(core)
    model = ScaraModel()
    reach = model.l1 + model.l2
    r_max_seen = max(math.hypot(x, y) for (x, y, _z, _rz) in samples)
    assert r_max_seen >= reach - 5.0, (r_max_seen, reach)
