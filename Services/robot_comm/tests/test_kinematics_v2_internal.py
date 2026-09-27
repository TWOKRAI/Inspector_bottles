"""Хазард-тесты автора модели робота (T2.K, `kinematics.py`) — не приёмка (та живёт
в `test_kinematics_v2.py`, написана вслепую тестером ДО реализации), а внутренние
опасности конкретно ЭТОЙ реализации: что может сломаться в закрытой формуле SCARA,
зная, как она устроена.
"""

from __future__ import annotations

import math

import pytest

from Services.robot_comm.core.params_v2 import PARAM_ID
from Services.robot_comm.core.protocol_v2 import ERR, KIND, OP, REASON, REG, REG_COUNT
from Services.robot_comm.kinematics import ScaraModel, make_model
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2

L1 = 325.0
L2 = 275.0
TOL = 1e-6

ACK = 1
NAK = 2

#: HOME по умолчанию (P_HOME_X/Y/Z/RZ) — фигурирует в нескольких тестах ниже.
HOME_POSE = (300.0, -210.0, -40.0, -100.0)


def u16(value: int) -> int:
    return value & 0xFFFF


def mm(eng: float) -> int:
    return round(eng * 10)


def cmd(core, seq: int, opcode: int, *args: int) -> dict:
    """Мини mailbox-хелпер — скопирован по паттерну test_kinematics_v2.py/test_sim_v2_motion.py."""
    core.write(REG["CMD_SEQ"], [u16(seq)])
    core.write(REG["CMD_OPCODE"], [opcode])
    core.write(REG["CMD_ARGC"], [len(args)])
    if args:
        core.write(REG["CMD_ARGS"], [u16(a) for a in args])
    core.write(REG["CMD_FLAG"], [1])
    core.tick()
    status = core.read(REG["RES_STATUS"], 1)[0]
    errno = core.read(REG["RES_ERRNO"], 1)[0]
    rvalc = core.read(REG["RES_RVALC"], 1)[0]
    rvals = core.read(REG["RES_RVALS"], REG_COUNT["RES_RVALS"])[:rvalc]
    return {"status": status, "errno": errno, "rvalc": rvalc, "rvals": rvals}


def servo_on(core, seq: int = 1) -> None:
    res = cmd(core, seq, OP["SERVO"], 1)
    assert res["status"] == ACK, "предусловие: серво должно включаться"


def test_ik_stretched_singularity_does_not_raise_on_float_c2_overshoot():
    """r чуть выше l1+l2 внутри допуска _REACH_TOL — c2 зажимается в [-1,1], acos не падает.

    Формула c2 = (r²-l1²-l2²)/(2 l1 l2) на самой границе досягаемости чувствительна к
    float-шуму сложения квадратов: без clamp acos(c2>1) кинул бы ValueError вместо
    возврата суставов. Проверяем и саму границу (r == l1+l2 ровно), и точку чуть
    дальше неё, но ещё внутри _REACH_TOL — обе обязаны вернуть суставы, не исключение.
    """
    model = ScaraModel(l1=L1, l2=L2)
    reach = L1 + L2
    for r in (reach, reach + 1e-10, math.nextafter(reach, reach + 1.0)):
        pose = (r, 0.0, -40.0, 0.0)
        for hand in (0, 1):
            joints = model.ik(pose, hand)  # не должно кидать ValueError из math.acos
            assert joints is not None, (r, hand)
            assert joints[1] == pytest.approx(0.0, abs=TOL), (r, hand, joints)


def test_ik_rejects_nan_and_inf_pose():
    """NaN/inf в любой координате позы -> None, а не тихий мусор или исключение из math.hypot/atan2."""
    model = ScaraModel(l1=L1, l2=L2)
    bad_poses = [
        (float("nan"), 0.0, -40.0, 0.0),
        (300.0, float("inf"), -40.0, 0.0),
        (300.0, 0.0, float("-inf"), 0.0),
        (300.0, 0.0, -40.0, float("nan")),
    ]
    for pose in bad_poses:
        for hand in (0, 1):
            assert model.ik(pose, hand) is None, (pose, hand)


def test_fk_ik_does_not_introduce_j4_wrap():
    """RZ, возвращённый fk(ik(pose, hand)), совпадает с исходным RZ БЕЗ ±360° сдвига.

    J4 = RZ - J1 - J2 в ik(), и обратное сложение в fk() обязано дать исходное RZ
    один-в-один (не эквивалентный угол по модулю 360°) — иначе окно-вида (T2.V) или
    следующая команда унаследуют скрытый разрыв суставного диапазона J4.
    """
    model = ScaraModel(l1=L1, l2=L2)
    for rz in (-370.0, -180.0, -1.0, 0.0, 1.0, 180.0, 359.0, 400.0):
        pose = (300.0, -210.0, -40.0, rz)
        for hand in (0, 1):
            joints = model.ik(pose, hand)
            assert joints is not None, (rz, hand)
            got_rz = model.fk(joints)[3]
            assert got_rz == pytest.approx(rz, abs=TOL), (rz, hand, joints, got_rz)


# =========================================================================== #
# JOG_CONT — проверка зоны на КАЖДОМ тике идёт через модель (не мимо неё)
# =========================================================================== #


class _AlwaysOutOfZoneModel:
    """Подставная модель — запрещает любую точку. JOG_CONT её не спрашивает при СТАРТЕ
    (`_op_jog_cont` не делает zone-check — только servo/hand/скорость), но самый первый
    тик прогресса хода (`_progress_jog`) обязан спросить модель ПЕРЕД тем, как сдвинуть
    позу. Раз модель запрещает всё — ход обрывается на первом же тике, поза не съезжает
    ни на шаг от домашней. `ik`/`joint_limits`/`joint_speed` делегированы реальной
    ScaraModel (T2.J2, минорная 6 ревью — `_boot()` безусловно зовёт `self.model.ik`)."""

    def __init__(self) -> None:
        self._real = ScaraModel()
        self.kind = self._real.kind
        self.axes = self._real.axes
        self.joint_names = self._real.joint_names
        self.joint_limits = self._real.joint_limits
        self.joint_speed = self._real.joint_speed

    def ik(self, pose, hand):
        return self._real.ik(pose, hand)

    def check_point(self, ws, pose):
        return REASON["R_OUT_OF_ZONE"]


def test_jog_cont_zone_check_goes_through_model():
    """JOG_CONT с моделью, запрещающей всё, -> ход завершается (DONE_SEQ==seq) на первом
    же тике, поза остаётся ровно домашней (не сдвигается ни на шаг).

    Живая `geometry.check_point` на дефолтной домашней позе разрешила бы шаг (поза внутри
    рабочей зоны) — JOG_CONT продолжал бы ехать несколько тиков подряд, пока не истечёт
    поводок (`P_JOG_LEASE_MS`, по умолчанию 300мс = 30 тиков по 10мс) или не упрётся в
    настоящую границу зоны. Значит остановка РОВНО на первом тике с неизменной позой —
    прямое доказательство, что `_progress_jog` спрашивает `self.model.check_point`, а не
    зовёт `geometry.check_point` напрямую (пропущенный вызов, найденный break-injection'ом
    ведущего на sim_core_v2.py: единственный не переведённый на модель зов зоны — T2.K)."""
    core = RobotSimCoreV2(model=_AlwaysOutOfZoneModel())
    servo_on(core, 1)
    home = core._read_pose_eng()

    res_start = cmd(core, 2, OP["JOG_CONT"], 1, 20)  # X+, 20 мм/с (<= P_JOG_CONT_MAX=50)
    assert res_start["status"] == ACK, res_start  # старт JOG_CONT модель не спрашивает

    for _ in range(3):  # "тик несколько раз с живым поводком" — после DONE это no-op
        core.tick()

    assert core.regs[REG["TLM_DONE_SEQ"]] == 2, "ход должен завершиться DONE на первом же тике"
    assert core.regs[REG["TLM_MOVING"]] == 0
    got = core._read_pose_eng()
    for exp_val, got_val in zip(home, got):
        assert got_val == pytest.approx(exp_val, abs=TOL), (home, got)


# =========================================================================== #
# LINE PTP_MOVE — проверка отрезка на КАЖДОМ ходе идёт через модель (не мимо неё)
# =========================================================================== #


class _DeadZoneOnSegmentModel:
    """check_point разрешает всё (0), check_segment — всегда R_DEAD_ZONE. Закрепляет,
    что `_check_motion` для LINE зовёт `self.model.check_segment`, а не напрямую
    `geometry.check_segment` (ревью T2.K находка 3: второе непроверенное место помимо
    JOG_CONT, которое закрыл test_jog_cont_zone_check_goes_through_model). `ik`/
    `joint_limits`/`joint_speed` делегированы реальной ScaraModel (T2.J2, минорная 6
    ревью — `_boot()` безусловно зовёт `self.model.ik`; тест шлёт LINE, предел
    суставов не проверяется, но объект обязан быть валидным duck-type ещё до этого)."""

    def __init__(self) -> None:
        self._real = ScaraModel()
        self.kind = self._real.kind
        self.axes = self._real.axes
        self.joint_names = self._real.joint_names
        self.joint_limits = self._real.joint_limits
        self.joint_speed = self._real.joint_speed

    def ik(self, pose, hand):
        return self._real.ik(pose, hand)

    def check_point(self, ws, pose):
        return 0

    def check_segment(self, ws, p0, p1):
        return REASON["R_DEAD_ZONE"]


def test_line_ptp_zone_check_goes_through_model():
    """LINE PTP_MOVE с моделью, запрещающей любой отрезок, -> NAK E_RANGE, rvals[0] ==
    R_DEAD_ZONE. Живая geometry.check_segment на этом же отрезке разрешила бы ход (обе
    точки внутри зоны, отрезок не проходит через мёртвую зону) — NAK возможен только
    если check() дошла до self.model.check_segment."""
    core = RobotSimCoreV2(model=_DeadZoneOnSegmentModel())
    servo_on(core, 1)

    res = cmd(core, 2, OP["PTP_MOVE"], mm(300.0), mm(-100.0), mm(-75.0), mm(0.0), KIND["LINE"], 100)
    assert res["status"] == NAK, res
    assert res["errno"] == ERR["E_RANGE"], res
    assert res["rvals"][0] == REASON["R_DEAD_ZONE"], res


# =========================================================================== #
# joints() — None достижим, источник TLM_* (не P_HOME/P_HAND) (ревью T2.K находки 1, 2)
# =========================================================================== #


def test_joints_none_when_zone_wider_than_model_reach():
    """joints() -> None — ДОСТИЖИМОЕ поведение (ревью T2.K находка 1), не баг: зона
    прошивки (P_WS_R_MAX) и досягаемость модели (|l1-l2|..l1+l2) — независимые границы.
    Репро ревью: P_WS_R_MAX=700мм (шире дефолтной досягаемости SCARA 600мм=l1+l2) ->
    JOINT-ход на (650,0) внутри новой зоны -> ACK -> joints() вне досягаемости модели -> None."""
    core = RobotSimCoreV2()
    servo_on(core, 1)
    res_ws = cmd(core, 2, OP["PARAM_SET"], PARAM_ID["P_WS_R_MAX"], u16(7000))
    assert res_ws["status"] == ACK, res_ws

    res_move = cmd(core, 3, OP["PTP_MOVE"], mm(650.0), mm(0.0), mm(-75.0), mm(0.0), KIND["JOINT"], 100)
    assert res_move["status"] == ACK, res_move
    for _ in range(200):  # MAX_STEP_MM ограничивает шаг/тик — довести ход до конца
        if core.regs[REG["TLM_MOVING"]] == 0:
            break
        core.tick()
    assert core.regs[REG["TLM_MOVING"]] == 0
    pose = core._read_pose_eng()
    assert pose[0] == pytest.approx(650.0, abs=0.1), pose  # ход дошёл до цели

    assert core.joints() is None


def test_joints_uses_tlm_hand_not_p_hand():
    """joints() решает IK с TLM_HAND (текущая рука исполнения), а не с P_HAND
    (конфигурационный параметр) — они расходятся, если PARAM_SET сменил P_HAND, но ни
    один JOINT-ход ещё не переставил TLM_HAND физически (ревью T2.K находка 2).
    Литерал числа — из репро ревью: TLM_HAND=1 (левая) на домашней позе -> J2 ≈ -105.29."""
    core = RobotSimCoreV2()
    assert core.regs[REG["TLM_HAND"]] == 1  # P_HAND дефолт=1 (левая), TLM_HAND зеркалит его при boot
    servo_on(core, 1)

    res = cmd(core, 2, OP["PARAM_SET"], PARAM_ID["P_HAND"], u16(0))
    assert res["status"] == ACK, res
    assert core._values[PARAM_ID["P_HAND"]] == 0  # P_HAND сменился...
    assert core.regs[REG["TLM_HAND"]] == 1  # ...а TLM_HAND — ещё нет (ход не выполнялся)

    joints = core.joints()
    assert joints is not None
    assert joints[1] < 0.0, joints  # TLM_HAND=1 (левая) -> J2 <= 0, а не P_HAND=0 (правая) -> J2 >= 0
    assert joints[1] == pytest.approx(-105.29424849603144, abs=1e-6), joints


def test_joints_uses_current_pose_not_home():
    """joints() решает IK от ТЕКУЩЕЙ TLM_* позы, а не от P_HOME_* (ревью T2.K находка 2).
    После хода в новую (не домашнюю) точку fk(joints()) обязан совпасть с НОВОЙ позой."""
    core = RobotSimCoreV2()
    servo_on(core, 1)
    target = (200.0, 100.0, -60.0, 20.0)
    res_move = cmd(
        core, 2, OP["PTP_MOVE"], mm(target[0]), mm(target[1]), mm(target[2]), mm(target[3]), KIND["JOINT"], 100
    )
    assert res_move["status"] == ACK, res_move
    for _ in range(200):
        if core.regs[REG["TLM_MOVING"]] == 0:
            break
        core.tick()
    pose = core._read_pose_eng()
    for exp_val, got_val in zip(target, pose):
        assert got_val == pytest.approx(exp_val, abs=0.1), (target, pose)
    assert any(abs(a - b) > 1.0 for a, b in zip(pose, HOME_POSE)), "цель должна отличаться от домашней позы"

    joints = core.joints()
    assert joints is not None
    fk_pose = make_model({"type": "scara"}).fk(joints)
    for exp_val, got_val in zip(pose, fk_pose):
        assert got_val == pytest.approx(exp_val, abs=0.1), (pose, fk_pose)


# =========================================================================== #
# hand вне {0,1} и make_model на границе (Dict at Boundary) — ревью T2.K находки 7, 8
# =========================================================================== #


def test_ik_rejects_hand_outside_scara_domain():
    """hand ∉ {0,1} -> ValueError, а не тихая подстановка "как правая" (ревью T2.K
    находка 7). До правки: ik((300,-210,-40,0), 2)[1] совпадал с hand=0 — недостижимо
    через sim (P_HAND ∈ [0,1]), но опасно при прямом использовании ScaraModel."""
    model = ScaraModel(l1=L1, l2=L2)
    for bad_hand in (2, -1, None):  # 0.0/1.0 не пробуем — равны 0/1 по `in`, легитимны
        with pytest.raises(ValueError, match="hand"):
            model.ik((300.0, -210.0, -40.0, 0.0), bad_hand)


def test_make_model_validates_link_lengths_and_unknown_keys():
    """Репро ревью T2.K находка 8 — все четыре сценария -> ValueError (не
    ZeroDivisionError/TypeError), сообщение называет проблемный ключ/значение."""
    with pytest.raises(ValueError, match="l1"):
        make_model({"type": "scara", "l1": 0})
    with pytest.raises(ValueError, match="l1"):
        make_model({"type": "scara", "l1": -325})
    with pytest.raises(ValueError, match="L1"):
        make_model({"type": "scara", "L1": 325.0})  # опечатка в ключе
    with pytest.raises(ValueError, match="l1"):
        make_model({"type": "scara", "l1": "325"})


def test_ik_j1_wrapped_to_controller_range() -> None:
    """J1 из `ik` лежит в (-180, 180] — так суставы репортует контроллер (ревью T2.K, итерация 2).

    Литерал: точка (-300, 50) левой рукой без обёртки давала J1 = 222.25°, с обёрткой −137.7535°.
    Граница: −180 заворачивается в +180 (полуинтервал открыт снизу).
    """
    from Services.robot_comm.kinematics import _wrap_deg

    model = ScaraModel()
    assert model.ik((-300.0, 50.0, 0.0, 0.0), 1)[0] == pytest.approx(-137.7535, abs=1e-4)
    assert _wrap_deg(-180.0) == 180.0
    assert _wrap_deg(180.0) == 180.0
    for r in (60.0, 200.0, 400.0, 599.0):
        for ang in range(-179, 181, 7):
            a = math.radians(ang)
            for hand in (0, 1):
                j = model.ik((r * math.cos(a), r * math.sin(a), 0.0, 0.0), hand)
                assert j is not None
                assert -180.0 < j[0] <= 180.0, (r, ang, hand, j)


# =========================================================================== #
# T2.J2 — валидация joint_limits/joint_speed и хелперы оборота J4 (автор)
# =========================================================================== #


def test_joint_limits_validation_rejects_bad_ranges() -> None:
    """`ScaraModel.__post_init__` (T2.J2 §Q1): `joint_limits` — длина по числу
    суставов, каждый элемент `None` или пара конечных `lo < hi`. Автор проверяет
    ЭТУ конкретную реализацию точечно (не через `make_model`, ту часть уже держит
    свойство 8 приёмки тестера) — сама валидация датакласса, до Dict-at-Boundary."""
    with pytest.raises(ValueError):
        ScaraModel(joint_limits=((-10.0, 10.0), None, None))  # длина 3, не 4
    with pytest.raises(ValueError):
        ScaraModel(joint_limits=((10.0, -10.0), None, None, None))  # lo >= hi
    with pytest.raises(ValueError):
        ScaraModel(joint_limits=((5.0, 5.0), None, None, None))  # lo == hi, не lo < hi
    with pytest.raises(ValueError):
        ScaraModel(joint_limits=((math.inf, 10.0), None, None, None))  # не конечное
    with pytest.raises(ValueError):
        ScaraModel(joint_limits=((-10.0,), None, None, None))  # не пара (lo, hi)
    # Валидный случай не падает (регрессионный якорь границы lo < hi строго).
    ScaraModel(joint_limits=((-10.0, 10.0), None, None, None))


def test_joint_speed_validation_rejects_non_positive() -> None:
    """`ScaraModel.__post_init__`: `joint_speed` — длина по числу суставов, каждый
    элемент конечное число > 0 (скорость <= 0 или NaN/inf сделала бы `_start_move`
    делить на неположительное/NaN молча, T2.J2 §Q3)."""
    with pytest.raises(ValueError):
        ScaraModel(joint_speed=(1.0, 1.0, 1.0))  # длина 3, не 4
    with pytest.raises(ValueError):
        ScaraModel(joint_speed=(1.0, 0.0, 1.0, 1.0))  # 0 — не > 0
    with pytest.raises(ValueError):
        ScaraModel(joint_speed=(1.0, -5.0, 1.0, 1.0))  # отрицательная
    with pytest.raises(ValueError):
        ScaraModel(joint_speed=(1.0, math.nan, 1.0, 1.0))  # NaN


def test_resolve_joint_target_keeps_j4_raw_no_turn() -> None:
    """`RobotSimCoreV2._resolve_joint_target` (T2.J2 §Q2, вердикт cto по RZ,
    `docs/reviews/2026-09-27_robot-v2-task-T2.J2-cto.md`): правило «J4 — ближайший
    оборот» ОТОЗВАНО — J4 остаётся СЫРЫМ (`rz - J1 - J2`, без перемотки ±360)
    везде. `j_end` внутри пределов -> возвращается КАК ЕСТЬ, J4 не трогается,
    даже когда он вне (-180,180] (бывший смысл «оборота»)."""
    core = RobotSimCoreV2(fw_build=1)
    j_end = (10.0, 0.0, 0.0, 535.0)  # J4=535 сырой, в пределе по умолчанию ±360? нет — 535>360.
    nak, resolved = core._resolve_joint_target(j_end)
    assert nak is not None, "535 вне дефолтного предела J4 ±360 -> NAK, без перемотки на 175.0"
    assert resolved is None

    j_end_in = (10.0, 0.0, 0.0, 300.0)  # в пределе ±360, сырой -> ACK без изменений.
    nak_ok, resolved_ok = core._resolve_joint_target(j_end_in)
    assert nak_ok is None
    assert resolved_ok == j_end_in, "j_end обязан вернуться БЕЗ изменений (J4 сырой, не оборот)"


def test_resolve_joint_target_j4_limit_none_accepts_any_raw() -> None:
    """Предел J4 = `None` -> сырой J4 любой величины проходит (свойство 5c приёмки
    тестера) — единый цикл по `joint_limits`, J4 не выделен особо."""
    model = make_model({"type": "scara", "joint_limits": [[-132.0, 132.0], [-150.0, 150.0], None, None]})
    core = RobotSimCoreV2(model=model)
    j_end = (10.0, 0.0, 0.0, 5341.0)
    nak, resolved = core._resolve_joint_target(j_end)
    assert nak is None
    assert resolved == j_end


def test_resolve_joint_target_checks_every_joint_not_only_j4() -> None:
    """`RobotSimCoreV2._resolve_joint_target` (T2.J2 §Q2): J4 разрешается оборотом
    первым, но НАК всё равно приходит и когда за пределом другой сустав (J1) —
    без этого проверка J4-оборота могла бы молча одобрить весь `j_end`, если код
    по ошибке проверял бы только J4 после его резолва."""
    core = RobotSimCoreV2(fw_build=1)
    lo_hi = core.model.joint_limits
    assert lo_hi[0] is not None and lo_hi[0][1] < 140.0, "предпосылка: J1 ограничен < 140° в дефолте"
    # J1 = 140 (за дефолтным пределом ±132), J4 = 10 (внутри предела, не требует оборота).
    j_end = (140.0, 0.0, 0.0, 10.0)
    nak, resolved = core._resolve_joint_target(j_end)
    assert resolved is None
    assert nak is not None
    assert nak[1] == ERR["E_RANGE"]
    assert nak[3] == [REASON["R_OUT_OF_ZONE"]]
    # Контрольный валидный j_end (все суставы внутри) не должен NAK'аться (регрессионный якорь).
    nak_ok, resolved_ok = core._resolve_joint_target((10.0, 0.0, 0.0, 10.0))
    assert nak_ok is None
    assert resolved_ok == (10.0, 0.0, 0.0, 10.0)
