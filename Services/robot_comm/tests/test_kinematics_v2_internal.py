"""Хазард-тесты автора модели робота (T2.K, `kinematics.py`) — не приёмка (та живёт
в `test_kinematics_v2.py`, написана вслепую тестером ДО реализации), а внутренние
опасности конкретно ЭТОЙ реализации: что может сломаться в закрытой формуле SCARA,
зная, как она устроена.
"""

from __future__ import annotations

import math

import pytest

from Services.robot_comm.core.protocol_v2 import OP, REASON, REG, REG_COUNT
from Services.robot_comm.kinematics import ScaraModel
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2

L1 = 325.0
L2 = 275.0
TOL = 1e-6

ACK = 1
NAK = 2


def u16(value: int) -> int:
    return value & 0xFFFF


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
