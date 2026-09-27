"""Хазард-тесты автора модели робота (T2.K, `kinematics.py`) — не приёмка (та живёт
в `test_kinematics_v2.py`, написана вслепую тестером ДО реализации), а внутренние
опасности конкретно ЭТОЙ реализации: что может сломаться в закрытой формуле SCARA,
зная, как она устроена.
"""

from __future__ import annotations

import math

import pytest

from Services.robot_comm.kinematics import ScaraModel

L1 = 325.0
L2 = 275.0
TOL = 1e-6


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
