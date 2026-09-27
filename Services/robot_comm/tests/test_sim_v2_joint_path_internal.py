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


# Тот же сценарий пересечения сектора, что у тестера (боевые дефолты) — T2.J2
# сменил точки (см. test_sim_v2_joint_path.py, докстринг CROSS_START/CROSS_TARGET
# и отчёт developer): оригинал брифинга T2.J давал J1(hand=1)=165.3° при
# дефолтном пределе ±132 — сама приёмка в CROSS_START стала NAK.
CROSS_START = (-320.2, -326.6, -75.0, 0.0)
CROSS_TARGET = (-30.8, 596.5, -75.0, 0.0)


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
        # T2.J2: ik() отдаёт не-None j_end для целей этого файла -> _check_motion
        # доходит до предела суставов -> нужны joint_limits/joint_speed (real
        # ScaraModel — тот же паттерн, что дефолт: пределы не мешают, скорость
        # заведомо огромна, декартов пол доминирует, как и раньше T2.J2).
        self.joint_limits = self._real.joint_limits
        self.joint_speed = self._real.joint_speed

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
    # Ведущий 2026-09-27 (T2.J2): порог reach-50, а не reach-5. Пик r у вытянутой руки узкий, а тики
    # с жёстким потолком шага ложатся по сетке, которая его перешагивает (замер: 590.2 при reach 600).
    # Инъекция, которую держит тест (конец пути без перекладки руки), даёт r не больше хорды — ~408 мм.
    assert r_max_seen >= reach - 50.0, (r_max_seen, reach)


def test_registered_pose_stays_in_zone_at_stretched_arm():
    """Поза в регистрах не выходит за r_max, когда суставный путь проходит вытянутую руку (T2.J2).

    Сторож ведущего 2026-09-27: у вытянутой руки fk даёт r = l1 + l2 = 600 = P_WS_R_MAX по умолчанию,
    округление x/y до 0.1 мм выносило позу на 600.03 — от неё ПК отверг бы следующую команду.
    Инъекция «снять клэмп позы к зоне в _progress_move» не валила ни один тест: поза (574.1, -174.4)
    на этом ходе (смена руки на 10%) выходила наружу молча.
    """
    from Services.robot_comm.programs.geometry import check_point
    from Services.robot_comm.tests.test_sim_v2_joint_path import cmd, servo_on, track_pose_until_done

    core = fresh_core()
    servo_on(core, 1)
    assert cmd(core, 2, OP["PARAM_SET"], PARAM_ID["P_HAND"], 0)["status"] == ACK
    assert cmd(core, 3, OP["PTP_MOVE"], 4000, 0, -400, 0, KIND["JOINT"], 10)["status"] == ACK
    samples = track_pose_until_done(core, max_ticks=2000)
    ws = core._workspace()  # дефолтные P_WS_*: r_max = 600
    outside = [p for p in samples if check_point(ws, *p) != 0]
    assert outside == [], outside[:3]


# =========================================================================== #
# Блокер 1 ревью T2.J2 — финальный тик тоже держит жёсткий потолок шага
# =========================================================================== #


def test_final_tick_respects_step_cap_after_hand_flip():
    """Ревьюер: P_HAND=0 JOINT (400,100), затем P_HAND=1 JOINT (400,140) — финальный
    тик прыгал в `target` в обход `_joint_tick_capped` (найден шаг 145.2мм при
    MAX_STEP_MM=33.3, `candidate_travelled >= path_len` шёл прямо на `target`/`j_end`).
    Каждый тик (включая финальный) обязан быть <= MAX_STEP_MM + 1e-6, ход обязан
    дойти до DONE за конечное число тиков."""
    core = fresh_core()
    servo_on(core, 1)
    assert cmd(core, 2, OP["PARAM_SET"], PARAM_ID["P_HAND"], u16(0))["status"] == ACK
    assert cmd(core, 3, OP["PTP_MOVE"], mm(400.0), mm(100.0), mm(-75.0), mm(0.0), KIND["JOINT"], 100)["status"] == ACK
    run_until_activity_zero(core)

    assert cmd(core, 4, OP["PARAM_SET"], PARAM_ID["P_HAND"], u16(1))["status"] == ACK
    res = cmd(core, 5, OP["PTP_MOVE"], mm(400.0), mm(140.0), mm(-75.0), mm(0.0), KIND["JOINT"], 100)
    assert res["status"] == ACK, res

    prev = pose_eng(core)
    max_ticks = 500
    for i in range(max_ticks):
        if core.read(REG["TLM_ACTIVITY"], 1)[0] == 0:
            break
        core.tick(TICK_S)
        cur = pose_eng(core)
        step = math.hypot(cur[0] - prev[0], cur[1] - prev[1])
        assert step <= 100 / 3 + 1e-6, f"тик {i}: шаг {step:.3f}мм больше MAX_STEP_MM"
        prev = cur
    else:
        pytest.fail(f"ход не завершился за {max_ticks} тиков")
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == 0
    assert pose_eng(core) == pytest.approx((400.0, 140.0, -75.0, 0.0), abs=0.1)


def test_short_chord_hand_flip_stays_under_step_cap():
    """Пара из брифа ревьюера: (400,100)->(410,100) со сменой руки — короткая хорда
    (10мм), проверяет ИМЕННО потолок шага (уже держит), не реализм `joint_speed`
    (тот факт, что вся суставная перекладка укладывается в 1 тик при дефолтном
    `joint_speed=1e9`, — решение ведущего 2026-09-27 «не трогать до cto», здесь не
    проверяется)."""
    core = fresh_core()
    servo_on(core, 1)
    assert cmd(core, 2, OP["PARAM_SET"], PARAM_ID["P_HAND"], u16(0))["status"] == ACK
    assert cmd(core, 3, OP["PTP_MOVE"], mm(400.0), mm(100.0), mm(-75.0), mm(0.0), KIND["JOINT"], 100)["status"] == ACK
    run_until_activity_zero(core)

    assert cmd(core, 4, OP["PARAM_SET"], PARAM_ID["P_HAND"], u16(1))["status"] == ACK
    prev = pose_eng(core)
    res = cmd(core, 5, OP["PTP_MOVE"], mm(410.0), mm(100.0), mm(-75.0), mm(0.0), KIND["JOINT"], 100)
    assert res["status"] == ACK, res
    cur = pose_eng(core)
    step = math.hypot(cur[0] - prev[0], cur[1] - prev[1])
    assert step <= 100 / 3 + 1e-6, f"шаг {step:.3f}мм больше MAX_STEP_MM"
    for i in range(500):
        if core.read(REG["TLM_ACTIVITY"], 1)[0] == 0:
            break
        prev = cur
        core.tick(TICK_S)
        cur = pose_eng(core)
        step = math.hypot(cur[0] - prev[0], cur[1] - prev[1])
        assert step <= 100 / 3 + 1e-6, f"тик {i}: шаг {step:.3f}мм больше MAX_STEP_MM"
    else:
        pytest.fail("ход не завершился за 500 тиков")
    assert pose_eng(core) == pytest.approx((410.0, 100.0, -75.0, 0.0), abs=0.1)


# =========================================================================== #
# Major 4 ревью T2.J2 — fk->None посреди пути не стирает состояние в None
# =========================================================================== #


class _FkFlakyRangeModel:
    """Делегирует всё в реальную ScaraModel, кроме `fk` — `None` только при `30<J1<40`
    (реплика репродукции ревьюера: узкая полоса недостижимости ПОСРЕДИ иначе тотальной
    `fk`, не всегда, как у `_FkFlakyModel`)."""

    def __init__(self) -> None:
        self._real = ScaraModel()
        self.kind = self._real.kind
        self.axes = self._real.axes
        self.joint_names = self._real.joint_names
        self.joint_limits = self._real.joint_limits
        self.joint_speed = self._real.joint_speed

    def fk(self, joints):
        if 30.0 < joints[0] < 40.0:
            return None
        return self._real.fk(joints)

    def ik(self, pose, hand):
        return self._real.ik(pose, hand)

    def chain_points(self, joints):
        return self._real.chain_points(joints)

    def check_point(self, ws, pose):
        return self._real.check_point(ws, pose)

    def check_segment(self, ws, p0, p1):
        return self._real.check_segment(ws, p0, p1)


def test_fk_none_mid_path_keeps_joint_state_not_none():
    """Major 4 ревью T2.J2: `fk -> None` ПОСРЕДИ пути (суставы из lerp двух ДОСТИЖИМЫХ
    концов сами не имеют `fk`) раньше стирал `self._joints` в `None` — после HARD-стопа
    `joints()` возвращал `None`, следующий JOINT стартовал БЕЗ состояния и шёл по прямой
    в Cartesian (не по суставам). Исправление: держать lerp суставов ПРИ ТЕКУЩЕМ (не
    продвинутом) `travelled`, а не стирать в `None`."""
    model = _FkFlakyRangeModel()
    core = RobotSimCoreV2(model=model)
    servo_on(core, 1)

    # Стартовая поза с J1=0 (вне полосы 30-40) — доехать туда обычным JOINT от HOME.
    start_j = (0.0, -90.0, -40.0, 0.0)
    start_pose = model.fk(start_j)
    assert (
        cmd(
            core,
            2,
            OP["PTP_MOVE"],
            mm(start_pose[0]),
            mm(start_pose[1]),
            mm(start_pose[2]),
            mm(start_pose[3]),
            KIND["JOINT"],
            100,
        )["status"]
        == ACK
    )
    run_until_activity_zero(core)

    # Ход J1: 0 -> 60, пересекает полосу 30-40, где fk возвращает None.
    target_j = (60.0, -90.0, -40.0, 0.0)
    target_pose = model.fk(target_j)
    res = cmd(
        core,
        3,
        OP["PTP_MOVE"],
        mm(target_pose[0]),
        mm(target_pose[1]),
        mm(target_pose[2]),
        mm(target_pose[3]),
        KIND["JOINT"],
        100,
    )
    assert res["status"] == ACK, res

    for _ in range(5):
        assert core.read(REG["TLM_ACTIVITY"], 1)[0] != 0, "предпосылка: ход ещё не завершился"
        core.tick(TICK_S)

    core.write(REG["STOP_REQ"], [STOP_LEVEL["HARD"]])
    core.tick(TICK_S)
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == 0
    joints = core.joints()
    assert joints is not None, "состояние не должно стираться в None при fk->None посреди пути"

    # Следующий JOINT идёт по суставам (заметно отклоняется от хорды к цели), а не
    # по прямой в Cartesian (что было бы, если бы j_start = None после обрыва).
    frozen = pose_eng(core)
    far_j = (frozen_j1 := joints[0] + 40.0, joints[1], joints[2], joints[3])
    far_pose = model.fk(far_j)
    res2 = cmd(
        core, 4, OP["PTP_MOVE"], mm(far_pose[0]), mm(far_pose[1]), mm(far_pose[2]), mm(far_pose[3]), KIND["JOINT"], 100
    )
    assert res2["status"] == ACK, res2
    samples = [pose_eng(core)]
    for _ in range(500):
        if core.read(REG["TLM_ACTIVITY"], 1)[0] == 0:
            break
        core.tick(TICK_S)
        samples.append(pose_eng(core))
    else:
        pytest.fail("ход не завершился за 500 тиков")
    max_dev = max(chord_perp_dist_xy(frozen[0], frozen[1], far_pose[0], far_pose[1], x, y) for x, y, _z, _rz in samples)
    assert max_dev > 5.0, (
        f"путь после стопа обязан идти по суставам (заметное отклонение от хорды), получено {max_dev:.3f}мм "
        f"(J1 старта {frozen_j1:.1f})"
    )


def test_explicit_large_dt_bounds_joint_progress_on_short_hand_flip():
    """Потолок доли пути за тик (min(speed*dt, MAX_STEP_MM)) держит СУСТАВЫ, а не только TCP (T2.J2).

    Сторож ведущего 2026-09-27: при смене руки на хорде 10 мм локоть проходит вытянутую руку, TCP почти стоит —
    декартов потолок шага суставы не ограничивает. Инъекция «снять MAX_STEP_MM в суставной ветке» не валила ни
    один тест: tick(1.0) проворачивал J2 почти целиком. Расчёт: ΔJ2 ≈ 182°, v_J2 = 720 × 0.7 -> 0.361 с,
    эквивалентная длина ≈ 541 мм, доля за тик ≤ 33.3/541 ≈ 6% -> ΔJ2 ≈ 11°; порог 20°.
    """
    from Services.robot_comm.tests.test_sim_v2_joint_path import cmd, servo_on, u16

    core = fresh_core()
    servo_on(core, 1)
    assert cmd(core, 2, OP["PARAM_SET"], PARAM_ID["P_HAND"], u16(0))["status"] == ACK
    assert cmd(core, 3, OP["PTP_MOVE"], 4000, 1000, 0, 0, KIND["JOINT"], 100)["status"] == ACK
    for _ in range(2000):
        if core.read(REG["TLM_ACTIVITY"], 1)[0] == 0:
            break
        core.tick(0.01)
    assert cmd(core, 4, OP["PARAM_SET"], PARAM_ID["P_HAND"], u16(1))["status"] == ACK
    assert cmd(core, 5, OP["PTP_MOVE"], 4100, 1000, 0, 0, KIND["JOINT"], 100)["status"] == ACK
    j2_before = core.joints()[1]
    core.tick(1.0)
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] != 0, "tick(1.0) не должен завершать смену руки"
    assert abs(core.joints()[1] - j2_before) <= 20.0, (j2_before, core.joints())
