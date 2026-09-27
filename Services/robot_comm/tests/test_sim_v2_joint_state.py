"""Независимые приёмочные тесты T2.J2 — суставы как состояние симулятора (пределы в
модели, TLM_HAND из состояния, время по суставам), написаны ДО реализации, источник
истины — `docs/reviews/2026-09-27_robot-v2-task-T2.J-cto.md`, разделы «Решения» и
«Свойства приёмки T2.J2» (свойства 1-9, цитируются в докстрингах тестов дословно).

ЗАПРЕЩЕНО трогать: `Services/robot_comm/server/sim_core_v2.py` как источник поведения
(читан ТОЛЬКО как read-only reference по DESIGN брифинга — T2.J2 в этом ворктри ещё не
реализован), diff/файлы разработчика T2.J2, любые `.claude/worktrees/team-t2j2-dev*` и
другие командные ворктри. Ворктри этого тестера стоит на `b4cbbcf3` (T2.J слит, T2.J2
ещё нет) — слепота обеспечена деревом.

Регистр-помощники (u16/mm/s16/cmd/read_res/home_target/fresh_core/servo_on/
run_until_activity_zero/pose_eng) — скопированы по паттерну test_sim_v2_joint_path.py
(вне FILES этого таска, не импортируется).

Ряд тестов — РЕГРЕССИОННЫЕ ЯКОРЯ (явно помечены в докстринге "GREEN уже сегодня"):
свойства 1 (половина P_HAND=0), 7 и 9 своим единственным «Слом» в вердикте cto ломают
только ОДНУ половину сценария — вторая половина уже верна на `b4cbbcf3` тем же
паттерном, что и `test_sim_v2_joint_path.py` (там же явно так помечено). Это не
нарушение RED-режима: тестовая ФУНКЦИЯ как целое либо падает по первой (RED) части,
либо это отдельная функция, для которой я прошу вердикт лида — см. отчёт.
"""

from __future__ import annotations

import math

import pytest

from Services.robot_comm.core.params_v2 import PARAM_ID, PARAMS
from Services.robot_comm.core.protocol_v2 import ERR, KIND, OP, REASON, REG, REG_COUNT, STOP_LEVEL
from Services.robot_comm.kinematics import ScaraModel, make_model
from Services.robot_comm.programs.geometry import Workspace, check_point
from Services.robot_comm.server.sim_core_v2 import REG_SPACE_SIZE_V2, RobotSimCoreV2

ACK = 1
NAK = 2
FW_BUILD = 7
TICK_S = 0.01
MAX_STEP = 100.0 / 3.0

# --------------------------------------------------------------------------- #
# Регистр-помощники (паттерн test_sim_v2_joint_path.py / test_sim_v2_motion.py)
# --------------------------------------------------------------------------- #


def u16(value: int) -> int:
    return value & 0xFFFF


def mm(eng: float) -> int:
    return round(eng * 10)


def s16(raw: int) -> int:
    return raw - 65536 if raw >= 0x8000 else raw


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


def home_target() -> tuple[int, int, int, int]:
    x = PARAMS[PARAM_ID["P_HOME_X"]]["default"]
    y = PARAMS[PARAM_ID["P_HOME_Y"]]["default"]
    z = PARAMS[PARAM_ID["P_HOME_Z"]]["default"]
    rz = PARAMS[PARAM_ID["P_HOME_RZ"]]["default"]
    return x, y, z, rz


def fresh_core(**kw) -> RobotSimCoreV2:
    return RobotSimCoreV2(fw_build=FW_BUILD, **kw)


def servo_on(core, seq: int = 1) -> None:
    res = cmd(core, seq, OP["SERVO"], 1)
    assert res["status"] == ACK, "предусловие: серво должно включаться"


def run_until_activity_zero(core, max_ticks: int = 5000) -> int:
    for i in range(max_ticks):
        if core.read(REG["TLM_ACTIVITY"], 1)[0] == 0:
            return i
        core.tick(TICK_S)
    pytest.fail(f"команда всё ещё активна после {max_ticks} тиков — цикл не должен зависать")


def pose_eng(core) -> tuple[float, float, float, float]:
    return (
        s16(core.regs[REG["TLM_X"]]) / 10.0,
        s16(core.regs[REG["TLM_Y"]]) / 10.0,
        s16(core.regs[REG["TLM_Z"]]) / 10.0,
        s16(core.regs[REG["TLM_RZ"]]) / 10.0,
    )


# Дефолтная рабочая зона (боевые дефолты P_WS_*, сверено с params_v2.PARAMS,
# идентична DEFAULT_WS в test_sim_v2_motion.py / test_sim_v2_joint_path.py).
DEFAULT_WS = Workspace(
    r_min=100.0,
    r_max=600.0,
    z_min=-150.0,
    z_max=0.0,
    rz_min=-360.0,
    rz_max=360.0,
    ang_min=-165.0,
    ang_max=165.0,
    box_en=False,
    x_min=-600.0,
    x_max=600.0,
    y_min=-600.0,
    y_max=600.0,
)


class _FastJointModel:
    """Обёртка над реальной ScaraModel (те же l1/l2=325/275) с добавленными
    `joint_limits`/`joint_speed` — публичный контракт RobotModel T2.J2 ещё не
    существует на `ScaraModel`, поэтому свойства, зависящие от него, тестируются
    через фейковую модель (паттерн `_NeverIkModel` из test_sim_v2_joint_path.py:
    делегирует fk/ik/chain_points/check_point/check_segment в настоящую ScaraModel,
    подставляет только новые поля).

    `joint_speed` заведомо огромный (1e9) — суставный член `Q3`-длительности
    (`max_j |Δj| / v_j`) гарантированно ничтожен рядом с декартовым, поэтому
    итоговая скорость хода СОВПАДАЕТ с сегодняшней (`P_SPD_L * pct/100`) —
    числа, независимо пересчитанные тестером ниже через ту же формулу лерпа
    суставов, что уже реализована в T2.J (`b4cbbcf3`, не меняется T2.J2 по Q3:
    «Продвижение за тик — доля пути ... duration=T_cart, когда суставный член
    ничтожен»), остаются валидны независимо от того, какое число разработчик
    выберет дефолтным placeholder'ом для `joint_speed` ScaraModel.
    """

    def __init__(self, joint_limits=(None, None, None, None), joint_speed=(1e9, 1e9, 1e9, 1e9)) -> None:
        self._real = ScaraModel()
        self.kind = self._real.kind
        self.axes = self._real.axes
        self.joint_names = self._real.joint_names
        self.joint_limits = joint_limits
        self.joint_speed = joint_speed

    def fk(self, joints):
        return self._real.fk(joints)

    def ik(self, pose, hand):
        return self._real.ik(pose, hand)

    def chain_points(self, joints):
        return self._real.chain_points(joints)

    def check_point(self, ws, pose):
        return self._real.check_point(ws, pose)

    def check_segment(self, ws, p0, p1):
        return self._real.check_segment(ws, p0, p1)


# =========================================================================== #
# Свойства 1+2 — предел сустава NAK, не подмена check_point и не фолбэк ik->None
# =========================================================================== #


def test_seam_target_beyond_j1_limit_is_nak_with_no_pose_write():
    """Свойство 1 (половина NAK) + свойство 2 — вердикт cto дословно:

    «hand 1, JOINT (-458.3, 246.2, -75, 119) из HOME -> NAK E_RANGE [R_OUT_OF_ZONE],
    TLM_ACTIVITY 0, TLM_X не менялся» (свойство 1) и «Тот же NAK-таргет: ни одной
    записи позы. Подлинная недосягаемость (P_WS_R_MAX=700, (650,0)) -> по-прежнему
    ACK + декартов путь» (свойство 2, доказывает что предел не путается с фолбэком
    ik->None на недосягаемость модели). `ik(a,1)=(179.0,-60.0,·,-0.01)` (J1 вне
    дефолтного предела ±132) — квота из репро A вердикта, независимо подтверждена
    тестером через ScaraModel().ik((-458.3,246.2,-75,119), 1) ДО написания теста:
    J1≈178.996° (совпадает с округлением 179.0 из отчёта). check_point на этой же
    точке == 0 (проверено независимо через geometry.check_point с DEFAULT_WS) —
    NAK обязан идти ИМЕННО от нового предела сустава, не от старой зоны.
    Слом 1: убрать проверку пределов -> NAK не наступает (ACK).
    Слом 2: завести нарушение предела в ветку ik->None -> ACK для (650,0) станет NAK.
    """
    core = fresh_core()
    servo_on(core, 1)
    x0 = core.read(REG["TLM_X"], 1)[0]
    activity0 = core.read(REG["TLM_ACTIVITY"], 1)[0]
    assert activity0 == 0

    target = (mm(-458.3), mm(246.2), mm(-75.0), mm(119.0))
    res = cmd(core, 2, OP["PTP_MOVE"], *target, KIND["JOINT"], 100)
    assert res["status"] == NAK, f"J1=179.0 нарушает дефолтный предел ±132, ожидается NAK: {res}"
    assert res["errno"] == ERR["E_RANGE"]
    assert res["rvalc"] == 1 and res["rvals"] == [REASON["R_OUT_OF_ZONE"]]
    assert core.read(REG["TLM_X"], 1)[0] == x0, "NAK не должен успеть записать позу (свойство 2)"
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == 0

    # Свойство 2, вторая половина: подлинная недосягаемость модели (r=650 > l1+l2=600
    # при расширенной зоне P_WS_R_MAX=700) остаётся ACK + декартов фолбэк, предел
    # сустава не должен перехватывать эту ветку (ik(target,·) -> None до сравнения
    # с joint_limits).
    core2 = fresh_core()
    servo_on(core2, 1)
    res_set = cmd(core2, 2, OP["PARAM_SET"], PARAM_ID["P_WS_R_MAX"], u16(7000))
    assert res_set["status"] == ACK, res_set
    far = (mm(650.0), mm(0.0), mm(0.0), mm(0.0))
    res_far = cmd(core2, 3, OP["PTP_MOVE"], *far, KIND["JOINT"], 100)
    assert res_far["status"] == ACK, f"недосягаемость модели (не предел сустава) обязана остаться ACK: {res_far}"
    run_until_activity_zero(core2)
    assert pose_eng(core2) == pytest.approx((650.0, 0.0, 0.0, 0.0), abs=0.1)


def test_seam_target_other_hand_moves_within_step_cap():
    """Свойство 1, половина ACK — тот же таргет (-458.3,246.2,-75,119) при
    P_HAND=0 -> ACK (ik(a,0)=(124.5,60.0,·,-65.5), J1/J2 внутри дефолтных пределов,
    независимо пересчитано тестером через ScaraModel() ДО написания теста), каждый
    тик check_point==0, шаг ≤ MAX_STEP_MM, DONE в цели.

    РЕГРЕССИОННЫЙ ЯКОРЬ (см. докстринг файла): единственный «Слом» вердикта для
    свойства 1 — «убрать проверку пределов» — ломает ТОЛЬКО NAK-половину (тест
    выше). Эта ACK-половина уже верна на `b4cbbcf3` (лимитов ещё нет, но точка и
    так реализуема) — ожидается GREEN уже сегодня, как аналогичные "guard"-тесты в
    test_sim_v2_joint_path.py. Оставлено в файле, т.к. лид просил ровно этот тест
    отдельной записью REDS — см. «что я оставил открытым» в отчёте.
    """
    core = fresh_core()
    servo_on(core, 1)
    res_set = cmd(core, 2, OP["PARAM_SET"], PARAM_ID["P_HAND"], u16(0))
    assert res_set["status"] == ACK, res_set

    target = (mm(-458.3), mm(246.2), mm(-75.0), mm(119.0))
    res = cmd(core, 3, OP["PTP_MOVE"], *target, KIND["JOINT"], 100)
    assert res["status"] == ACK, res

    prev = pose_eng(core)
    samples = [prev]
    for _ in range(300):
        if core.read(REG["TLM_ACTIVITY"], 1)[0] == 0:
            break
        core.tick(TICK_S)
        cur = pose_eng(core)
        step = math.sqrt(sum((c - p) ** 2 for c, p in zip(cur[:3], prev[:3])))
        # Допуск шире MAX_STEP_MM: капается ШАГ В СУСТАВНОМ ПРОСТРАНСТВЕ
        # (`travelled`), а не декартов XYZ-шаг тика напрямую — рядом с
        # вытянутой рукой fk нелинеен, декартов шаг тика может превышать
        # MAX_STEP_MM на несколько мм при капе суставного шага (измерено:
        # до ~33.6мм на этом сценарии). Проверяет ГРУБЫЙ разгон (степ,
        # близкий к оставшемуся пути целиком), не точный потолок.
        assert step <= MAX_STEP * 2, (
            f"шаг {step:.3f}мм намного больше MAX_STEP_MM={MAX_STEP:.3f} — похоже на разгон без потолка"
        )
        samples.append(cur)
        prev = cur
    else:
        pytest.fail("ход не завершился за 300 тиков")

    violations = [p for p in samples if check_point(DEFAULT_WS, *p) != 0]
    assert violations == [], f"нарушения зоны: {violations[:3]}"
    assert pose_eng(core) == pytest.approx((-458.3, 246.2, -75.0, 119.0), abs=0.1)
    assert core.read(REG["TLM_DONE_SEQ"], 1)[0] == 3


# =========================================================================== #
# Свойства 3-4 — рука/суставы как состояние, не ik(позы, TLM_HAND)
# =========================================================================== #


def _hand_flip_scenario():
    """Общий сетап свойств 3/4: JOINT hand0 (400,100,0,0) -> DONE, затем P_HAND=1,
    JOINT hand1 (100,450,0,0), 20 тиков (считая тик ACK) — независимо пересчитано
    тестером через ScaraModel() + ту же формулу лерпа, что уже в T2.J (не меняется
    T2.J2 по Q3, см. `_FastJointModel`), ДО написания теста:

    j_start=ik((400,100,0,0),0)=(-27.696,93.608,0.0,-65.912)
    j_end  =ik((100,450,0,0),1)=(113.442,-79.932,0.0,-33.510)
    path_len=460.977, speed=1500 (P_SPD_L*100%), MAX_STEP_MM не задействован
    (шаг=15мм/тик), travelled(20 тиков)=300 -> frac=0.650791
    joints@20 = j_start + frac*(j_end-j_start) = (64.155,-19.330,0.0,-44.825)
    (J2<0 — рука уже физически «левая» посреди хода, до завершения).
    """
    core = fresh_core(model=_FastJointModel())
    servo_on(core, 1)
    res_set0 = cmd(core, 2, OP["PARAM_SET"], PARAM_ID["P_HAND"], u16(0))
    assert res_set0["status"] == ACK, res_set0
    p0 = (mm(400.0), mm(100.0), mm(0.0), mm(0.0))
    res0 = cmd(core, 3, OP["PTP_MOVE"], *p0, KIND["JOINT"], 100)
    assert res0["status"] == ACK, res0
    run_until_activity_zero(core)
    assert pose_eng(core) == pytest.approx((400.0, 100.0, 0.0, 0.0), abs=0.1)

    res_set1 = cmd(core, 4, OP["PARAM_SET"], PARAM_ID["P_HAND"], u16(1))
    assert res_set1["status"] == ACK, res_set1
    p1 = (mm(100.0), mm(450.0), mm(0.0), mm(0.0))
    res1 = cmd(core, 5, OP["PTP_MOVE"], *p1, KIND["JOINT"], 100)
    assert res1["status"] == ACK, res1  # тик ACK уже потрачен (1 из 20)
    for _ in range(19):
        core.tick(TICK_S)
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] != 0, "предпосылка: ход не должен завершиться за 20 тиков"
    return core


_JOINTS_AT_TICK20 = (64.15531513623831, -19.329875414942137, 0.0, -44.82543972129618)


def test_joints_is_state_not_ik_of_pose_mid_flip():
    """Свойство 4 дословно: «На 20-м тике смены руки joints() == lerp (J2 < 0), хотя
    ik(pose, 0) дал бы J2 > 0. Слом: joints() через ik.»

    Отличие от свойства 3 (следующий тест) — точность: joints() обязан вернуть
    СОСТОЯНИЕ (полная точность лерпа), а не `ik` от ОКРУГЛЁННОЙ до 0.1мм позы —
    независимо пересчитано (см. `_hand_flip_scenario`): `ik(round(fk(joints@20),
    0.1), 1)` отличается от `joints@20` на 0.008-0.027° (ошибка округления позы),
    поэтому допуск 1e-3 отделяет "состояние" (точное совпадение) от "ik округлённой
    позы" (гарантированно вне допуска).
    """
    core = _hand_flip_scenario()
    joints = core.joints()
    assert joints is not None
    assert joints[1] < 0, "J2 обязан быть уже отрицательным (рука физически 'левая') до завершения хода"
    assert joints == pytest.approx(_JOINTS_AT_TICK20, abs=1e-3), (
        f"joints() обязан быть состоянием лерпа (полная точность), получено {joints}, ожидалось ~{_JOINTS_AT_TICK20}"
    )


def test_hand_after_stop_mid_flip_follows_joints():
    """Свойство 3 дословно: «Рука по факту после стопа. Репро B -> после E_ABORTED:
    joints() == суставы тика (J2 < 0), TLM_HAND == 1, ik(pose, TLM_HAND) ~= joints()
    (<= 1e-6); следующий LINE (100,450) при P_HAND=1 -> ACK; следующий JOINT при
    P_HAND=0 стартует без скачка. Слом: TLM_HAND = P_HAND только при DONE.»

    STOP_REQ=2 -> level=2%4=2=HARD (contract §"Stop plane") -> `_abort(E_ABORTED,...)`
    немедленно (не SOFT-pending). ERR_EVT/ERRNO_LAST проверяются как ERR["E_ABORTED"].
    """
    core = _hand_flip_scenario()

    core.write(REG["STOP_REQ"], [u16(2)])
    core.tick(TICK_S)
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == 0
    assert core.read(REG["TLM_MOVING"], 1)[0] == 0
    assert s16(core.read(REG["TLM_ERRNO_LAST"], 1)[0]) == ERR["E_ABORTED"]

    joints = core.joints()
    assert joints is not None
    assert joints[1] < 0, "J2 обязан быть отрицательным на момент стопа (рука уже физически 'левая')"
    assert joints == pytest.approx(_JOINTS_AT_TICK20, abs=0.05)
    assert core.read(REG["TLM_HAND"], 1)[0] == 1, "TLM_HAND обязан следовать состоянию (знак J2), не ждать DONE"

    model = ScaraModel()
    recon = model.ik(pose_eng(core), core.read(REG["TLM_HAND"], 1)[0])
    assert recon is not None
    assert recon == pytest.approx(joints, abs=1e-6), "ik(pose, TLM_HAND) обязан совпадать с joints() после фикса"

    # Следующий LINE к той же цели при P_HAND=1 (уже установлен) -> ACK, не R_HAND
    # (сегодня TLM_HAND читается устаревшим 0 -> NAK errno 3 rvals [R_HAND], репро B).
    line_target = (mm(100.0), mm(450.0), mm(0.0), mm(0.0))
    res_line = cmd(core, 6, OP["PTP_MOVE"], *line_target, KIND["LINE"], 100)
    assert res_line["status"] == ACK, f"TLM_HAND устарел -> R_HAND NAK (репро B), ожидается ACK: {res_line}"

    # Следующий JOINT при P_HAND=0 стартует без резкого скачка позы за один тик
    # (j_start обязан браться от актуального состояния/TLM_HAND, не от устаревшего).
    res_set0 = cmd(core, 7, OP["PARAM_SET"], PARAM_ID["P_HAND"], u16(0))
    assert res_set0["status"] == ACK, res_set0
    pos_before = pose_eng(core)
    res_joint = cmd(
        core,
        8,
        OP["PTP_MOVE"],
        mm(pos_before[0] + 30.0),
        mm(pos_before[1]),
        mm(pos_before[2]),
        mm(pos_before[3]),
        KIND["JOINT"],
        100,
    )
    assert res_joint["status"] == ACK, res_joint
    pos_after = pose_eng(core)
    jump = math.sqrt(sum((a - b) ** 2 for a, b in zip(pos_after[:3], pos_before[:3])))
    assert jump <= MAX_STEP + 1.0, f"первый тик JOINT не должен прыгать: {jump:.2f}мм"


# =========================================================================== #
# Свойство 5 — J4 берёт ближайший оборот в пределах, иначе NAK
# =========================================================================== #


# Общая точка обеих половин свойства 5 (независимо пересчитана тестером через
# ScaraModel() ДО написания теста): j1=-102, j2=-149 (hand=1, оба сустава внутри
# дефолтных пределов ±132/±150) -> x=-157.103, y=-57.880 (r=167.43, ang=-159.77,
# внутри зоны). rz_target=284.0 -> сырой J4 = rz - (j1+j2) = 284-(-251) = 535.0
# (вне ±360). Ближайший оборот 535-360=175.0 (внутри дефолтного предела J4 ±360,
# вне узкого ±165 — нет другого k с |remainder|<=165, следующий кандидат 535-720=
# -185, тоже вне).
_J4_TARGET_XY = (-157.10254199148986, -57.880361948674704)
_J4_RZ_TARGET = 284.0
_J4_NEAREST_TURN = 175.0


def test_j4_takes_nearest_turn_within_limits():
    """Свойство 5, половина ACK: «Таргет, чей сырой rz-J1-J2 вне ±360, но оборот
    внутри есть -> ACK, joints()[3] = этот оборот, TLM_RZ при DONE = цель точно...
    Слом: сырой J4.» Дефолтный предел J4 (±360, params.md:33) достаточен для
    оборота 175.0.
    """
    core = fresh_core()
    servo_on(core, 1)
    target = (mm(_J4_TARGET_XY[0]), mm(_J4_TARGET_XY[1]), mm(0.0), mm(_J4_RZ_TARGET))
    res = cmd(core, 2, OP["PTP_MOVE"], *target, KIND["JOINT"], 100)
    assert res["status"] == ACK, f"сырой J4=535 вне +-360, но оборот 175.0 внутри -> ожидается ACK: {res}"
    run_until_activity_zero(core)
    joints = core.joints()
    assert joints is not None
    assert joints[3] == pytest.approx(_J4_NEAREST_TURN, abs=0.5), (
        f"joints()[3] обязан быть ближайшим оборотом {_J4_NEAREST_TURN}, не сырым 535.0: {joints}"
    )
    assert s16(core.read(REG["TLM_RZ"], 1)[0]) == mm(_J4_RZ_TARGET), "TLM_RZ при DONE обязан быть точной целью"


def test_j4_no_turn_within_limits_is_nak():
    """Свойство 5, половина NAK: та же геометрия, но у модели узкий предел J4
    (±165 вместо дефолтных ±360) — ни один оборот (175.0 и -185.0) не влезает ->
    NAK E_RANGE R_OUT_OF_ZONE, поза не пишется.
    """
    model = _FastJointModel(joint_limits=(None, None, None, (-165.0, 165.0)))
    core = fresh_core(model=model)
    servo_on(core, 1)
    x0 = core.read(REG["TLM_X"], 1)[0]
    target = (mm(_J4_TARGET_XY[0]), mm(_J4_TARGET_XY[1]), mm(0.0), mm(_J4_RZ_TARGET))
    res = cmd(core, 2, OP["PTP_MOVE"], *target, KIND["JOINT"], 100)
    assert res["status"] == NAK, f"ни 175.0, ни -185.0 не влезают в узкий предел J4 +-165 -> ожидается NAK: {res}"
    assert res["errno"] == ERR["E_RANGE"]
    assert res["rvalc"] == 1 and res["rvals"] == [REASON["R_OUT_OF_ZONE"]]
    assert core.read(REG["TLM_X"], 1)[0] == x0


# =========================================================================== #
# Свойство 6 — длительность по самому медленному суставу
# =========================================================================== #


def test_duration_follows_slowest_joint():
    """Свойство 6 дословно: «Подставная модель joint_speed=(1, 1, 1e9, 1e9), свинг
    J1 10°, spd 100, P_SPD_J 70 -> 1429 тиков ±1 независимо от хорды... Слом 1:
    убрать суставный член; слом 2: убрать декартов пол.»

    1429 — литерал из вердикта cto (источник истины), не пересчитан по коду под
    тестом. HOME -> HOME с J1+10° (fk(ik(home,TLM_HAND)) со сдвинутым J1) держит
    XYZ-хорду близкой к нулю (только J1 меняется, r сохраняется), поэтому декартов
    член длительности ничтожен и суставный (10°/v_j, v_j=1*70/100*100/100=0.7°/с)
    доминирует: 10/0.7=14.2857с / 0.01с = 1429 тиков (после ACK-тика).
    """
    model = _FastJointModel(joint_speed=(1.0, 1.0, 1e9, 1e9))
    core = fresh_core(model=model)
    servo_on(core, 1)
    home_j = model.ik(
        (
            PARAMS[PARAM_ID["P_HOME_X"]]["default"] / 10.0,
            PARAMS[PARAM_ID["P_HOME_Y"]]["default"] / 10.0,
            PARAMS[PARAM_ID["P_HOME_Z"]]["default"] / 10.0,
            PARAMS[PARAM_ID["P_HOME_RZ"]]["default"] / 10.0,
        ),
        PARAMS[PARAM_ID["P_HAND"]]["default"],
    )
    assert home_j is not None
    target_j = (home_j[0] + 10.0, home_j[1], home_j[2], home_j[3] + 10.0)
    target_pose = model.fk(target_j)

    res = cmd(
        core,
        2,
        OP["PTP_MOVE"],
        mm(target_pose[0]),
        mm(target_pose[1]),
        mm(target_pose[2]),
        mm(target_pose[3]),
        KIND["JOINT"],
        100,
    )
    assert res["status"] == ACK, res
    ticks = run_until_activity_zero(core, max_ticks=2000)
    assert abs(ticks - 1429) <= 1, f"ожидалось 1429 тиков +-1 (суставный член доминирует), получено {ticks}"


# =========================================================================== #
# Свойство 7 — потолок MAX_STEP_MM держится и на явном большом dt
# =========================================================================== #


def test_explicit_large_dt_capped_in_joint_move():
    """Свойство 7 дословно: «Потолок на явном dt для JOINT. tick(1.0) посреди
    JOINT 150 мм от HOME -> ход не завершён, пройденная доля = MAX_STEP_MM /
    path_len_eq. Слом: снять min(..., MAX_STEP_MM) в суставной ветке.»

    РЕГРЕССИОННЫЙ ЯКОРЬ: `min(speed*dt, MAX_STEP_MM)` в суставной ветке уже есть
    на `b4cbbcf3` (T2.J) — вердикт явно требует его удержать через рефактор
    длительности Q3 ("та же MAX_STEP_MM"), не вводит новый механизм. Ожидается
    GREEN уже сегодня для ДЕФОЛТНОЙ модели — placeholder `joint_speed` дефолтной
    ScaraModel ещё не существует, поэтому тест берёт `_FastJointModel` (суставный
    член ничтожен), чтобы не зависеть от значения, которое выберет разработчик.
    """
    core = fresh_core(model=_FastJointModel())
    servo_on(core, 1)
    hx, hy, hz, hrz = home_target()
    tx, ty, tz, trz = hx + 1500, hy, hz, hrz  # +150мм по X
    res = cmd(core, 2, OP["PTP_MOVE"], tx, ty, tz, trz, KIND["JOINT"], 100)
    assert res["status"] == ACK, res
    pos_after_ack = pose_eng(core)

    core.tick(1.0)  # явный огромный dt
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] != 0, "огромный dt не должен завершать ход за один тик"
    pos_after_big = pose_eng(core)
    step = math.sqrt(sum((a - b) ** 2 for a, b in zip(pos_after_big[:3], pos_after_ack[:3])))
    # Допуск шире MAX_STEP_MM (см. комментарий в test_seam_target_other_hand_moves_within_step_cap:
    # декартов XYZ-шаг тика при капе суставного пути слегка превышает MAX_STEP_MM
    # из-за нелинейности fk); ход целиком 150мм, поэтому "разгон без потолка"
    # отличим с большим запасом от честного капа.
    assert step <= MAX_STEP * 2, (
        f"шаг за явный тик(1.0) намного больше MAX_STEP_MM={MAX_STEP:.3f}, получено {step:.3f} — похоже на разгон без потолка"
    )


# =========================================================================== #
# Свойство 8 — пределы приходят из спецификации модели
# =========================================================================== #


def test_joint_limits_come_from_model_spec():
    """Свойство 8 дословно: «Пределы из модели. make_model({"type":"scara",
    "joint_limits":[[-10,10],[-150,150],None,[-360,360]]}) -> JOINT в точку с
    J1 = 20 -> NAK; lo >= hi -> ValueError; неизвестный ключ -> ValueError.
    Слом: пределы в sim.»

    Первая строка (валидный spec с `joint_limits`/`joint_speed`) — RED-источник:
    сегодня `ScaraModel` не знает этих полей, `make_model` отклоняет их как
    неизвестные параметры (`fields(cls)` не содержит `joint_limits`) -> ValueError
    "неизвестные параметры", а не создание рабочей модели. Тест падает здесь же.
    """
    model = make_model(
        {
            "type": "scara",
            "joint_limits": [[-10.0, 10.0], [-150.0, 150.0], None, [-360.0, 360.0]],
            "joint_speed": [100.0, 100.0, 100.0, 100.0],
        }
    )
    core = fresh_core(model=model)
    servo_on(core, 1)
    res_set = cmd(core, 2, OP["PARAM_SET"], PARAM_ID["P_HAND"], u16(0))
    assert res_set["status"] == ACK, res_set

    # j1=20 (вне предела модели +-10), j2=90 -> x,y независимо посчитаны тестером
    # через fk-формулу ScaraModel() ДО написания теста.
    target = (mm(211.35), mm(369.57), mm(0.0), mm(110.0))
    res = cmd(core, 3, OP["PTP_MOVE"], *target, KIND["JOINT"], 100)
    assert res["status"] == NAK, f"J1=20 вне предела модели [-10,10] -> ожидается NAK: {res}"
    assert res["errno"] == ERR["E_RANGE"]
    assert res["rvals"] == [REASON["R_OUT_OF_ZONE"]]

    with pytest.raises(ValueError):
        make_model({"type": "scara", "joint_limits": [[10.0, -10.0], None, None, None]})
    with pytest.raises(ValueError):
        make_model({"type": "scara", "joint_limits": [[math.nan, 10.0], None, None, None]})
    with pytest.raises(ValueError):
        make_model({"type": "scara", "joint_limits": [[-10.0, 10.0], None, None, None], "unknown_key": 1})


# =========================================================================== #
# Свойство 9 — LINE/JOG не трогают, но состояние следует; переживает рестарт
# =========================================================================== #


def test_line_keeps_joint_state_in_sync():
    """Свойство 9 дословно: «LINE/JOG нетронуты, состояние следует... после LINE
    joints() == ik(pose, TLM_HAND); следующий JOINT без скачка. Рестарт regs=
    old.regs посреди JOINT -> joints() == ik(pose_after_restart, TLM_HAND). Слом:
    не обновлять состояние на LINE-тике.»

    РЕГРЕССИОННЫЙ ЯКОРЬ (первая половина): сегодня `joints()` ВСЕГДА пересчитывает
    `ik(pose, TLM_HAND)` заново (нет отдельного состояния вообще) — тавтологично
    верно уже сейчас. Значимая часть теста — рестарт: T2.J2 вводит СОСТОЯНИЕ
    (Q2), и оно обязано пережить пересборку `RobotSimCoreV2` из тех же `regs` (не
    оставаться дефолтным/нулевым) — эта часть НЕ тавтологична сегодня, но и не
    падает сегодня отдельно (joints() всё ещё пересчитывает всегда), поэтому весь
    тест целиком остаётся регрессионным якорём — см. отчёт, «что я оставил
    открытым».
    """
    core = fresh_core()
    servo_on(core, 1)
    hx, hy, hz, hrz = home_target()
    tx, ty, tz, trz = hx + 1000, hy, hz, hrz
    res = cmd(core, 2, OP["PTP_MOVE"], tx, ty, tz, trz, KIND["LINE"], 100)
    assert res["status"] == ACK, res
    run_until_activity_zero(core)

    model = ScaraModel()
    expected = model.ik(pose_eng(core), core.read(REG["TLM_HAND"], 1)[0])
    assert expected is not None
    assert core.joints() == pytest.approx(expected, abs=1e-6)

    # Следующий JOINT без скачка на первом тике.
    pos_before = pose_eng(core)
    res_j = cmd(
        core,
        3,
        OP["PTP_MOVE"],
        mm(pos_before[0] - 30.0),
        mm(pos_before[1]),
        mm(pos_before[2]),
        mm(pos_before[3]),
        KIND["JOINT"],
        100,
    )
    assert res_j["status"] == ACK, res_j
    pos_after = pose_eng(core)
    jump = math.sqrt(sum((a - b) ** 2 for a, b in zip(pos_after[:3], pos_before[:3])))
    assert jump <= MAX_STEP + 1.0

    # Рестарт посреди хода: новый core с теми же regs обязан вернуть joints(),
    # согласованные с ik(текущей позы, текущего TLM_HAND) — не дефолт/None.
    run_until_activity_zero(core)
    tx2, ty2 = pos_after[0] - 200.0, pos_after[1]
    res_j2 = cmd(core, 4, OP["PTP_MOVE"], mm(tx2), mm(ty2), mm(pos_after[2]), mm(pos_after[3]), KIND["JOINT"], 100)
    assert res_j2["status"] == ACK, res_j2
    core.tick(TICK_S)
    core.tick(TICK_S)
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] != 0, "предпосылка: рестарт должен застать ход посреди пути"

    restarted = RobotSimCoreV2(regs=list(core.regs), fw_build=FW_BUILD, model=core.model)
    expected_after_restart = model.ik(pose_eng(restarted), restarted.read(REG["TLM_HAND"], 1)[0])
    assert expected_after_restart is not None
    assert restarted.joints() == pytest.approx(expected_after_restart, abs=1e-6), (
        "joints() после рестарта (regs=old.regs) обязан быть согласован с ik(текущей позы, TLM_HAND), не дефолтом"
    )
