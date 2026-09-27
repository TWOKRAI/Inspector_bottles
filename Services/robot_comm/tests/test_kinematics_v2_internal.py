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
    ни на шаг от домашней."""

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
    JOG_CONT, которое закрыл test_jog_cont_zone_check_goes_through_model)."""

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
