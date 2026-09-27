"""Независимые приёмочные тесты модели робота (T2.K — `Services/robot_comm/kinematics.py`),
написанные ДО реализации по брифу `plans/robot-protocol-v2/tasks.md` (раздел "### T2.K").

Источник истины — бриф T2.K (переданный ведущим дословно), не сама реализация: `kinematics.py`
ещё не существует в этом ворктри (коммит c2a5c28f, до T2.K). `Services/robot_comm/kinematics`
НЕ импортируется на уровне модуля — иначе один ModuleNotFoundError убил бы сбор всего файла и
приёмка не увидела бы 10 отдельных тестов. Вместо этого каждый тест, которому нужен
`kinematics.py`, импортирует его лениво внутри себя: падает только этот тест
(ModuleNotFoundError, подкласс ImportError), с собственной трассировкой.

`RobotSimCoreV2` (`server/sim_core_v2.py`) уже существует с T2.1/T2.2 (конструктор
`(regs=None, *, fw_build=0)`, без `model=`) — импортируется на уровне модуля безопасно;
тесты, использующие `model=`, падают TypeError на неизвестном kwarg, а не ImportError.

ЗАПРЕЩЕНО трогать (не открывать, не grep'ать, не импортировать): будущий `kinematics.py`
(его не существует), любую implementation-ветку задачи T2.K вне уже принятых T2.0-T2.2
файлов, названных в брифе как read-only reference.

Числа зоны — "боевые" дефолты `params_v2.PARAMS` (P_WS_*), переведённые в инженерные единицы
через `to_eng` (не литералы) — см. `test_zone_checks_delegate_to_geometry`.
"""

from __future__ import annotations

import math

import pytest

from Services.robot_comm.core.params_v2 import PARAM_ID, PARAMS, to_eng
from Services.robot_comm.core.protocol_v2 import ERR, KIND, OP, REASON, REG, REG_COUNT
from Services.robot_comm.programs.geometry import Workspace, check_point, check_segment
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2

L1 = 325.0
L2 = 275.0
TOL = 1e-6

# ACK/NAK — литералы, как во всех T2.x тестах (контракт называет их числом).
ACK = 1
NAK = 2


def _make_scara() -> object:
    """Ленивый импорт ScaraModel — модуль kinematics.py ещё не существует (ожидаемый RED)."""
    from Services.robot_comm.kinematics import ScaraModel

    return ScaraModel(l1=L1, l2=L2)


# --------------------------------------------------------------------------- #
# Мини mailbox-хелперы — скопированы по паттерну test_sim_v2_motion.py (файл вне
# FILES этой задачи, только прочитан за стилем; не импортирован).
# --------------------------------------------------------------------------- #


def u16(value: int) -> int:
    return value & 0xFFFF


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
    status = core.read(REG["RES_STATUS"], 1)[0]
    errno = core.read(REG["RES_ERRNO"], 1)[0]
    rvalc = core.read(REG["RES_RVALC"], 1)[0]
    rvals = core.read(REG["RES_RVALS"], REG_COUNT["RES_RVALS"])[:rvalc]
    return {"status": status, "errno": errno, "rvalc": rvalc, "rvals": rvals}


def servo_on(core, seq: int = 1) -> None:
    res = cmd(core, seq, OP["SERVO"], 1)
    assert res["status"] == ACK, "предусловие: серво должно включаться"


def home_target() -> tuple[int, int, int, int]:
    return (
        PARAMS[PARAM_ID["P_HOME_X"]]["default"],
        PARAMS[PARAM_ID["P_HOME_Y"]]["default"],
        PARAMS[PARAM_ID["P_HOME_Z"]]["default"],
        PARAMS[PARAM_ID["P_HOME_RZ"]]["default"],
    )


# =========================================================================== #
# FK/IK — закрытая формула SCARA
# =========================================================================== #


def test_fk_ik_roundtrip_both_hands():
    """fk(ik(p, h)) == p (±1e-6) для обеих рук на сетке точек зоны (бриф T2.K, приёмка п.1).

    Сетка — обычные вложенные циклы (hypothesis не установлен в этом окружении).
    r строго между |l1-l2|=50 и l1+l2=600 — вдали от особых точек границы
    (граница r==l1+l2 проверяется отдельным тестом ниже).
    """
    model = _make_scara()
    z, rz = -40.0, 10.0
    for r in (60.0, 100.0, 200.0, 325.0, 400.0, 500.0, 599.0):
        for angle_deg in range(-150, 151, 30):
            angle = math.radians(angle_deg)
            pose = (r * math.cos(angle), r * math.sin(angle), z, rz)
            for hand in (0, 1):
                joints = model.ik(pose, hand)
                assert joints is not None, (r, angle_deg, hand)
                got = model.fk(joints)
                for expected, actual in zip(pose, got):
                    assert actual == pytest.approx(expected, abs=TOL), (r, angle_deg, hand, pose, got)


def test_hands_differ_by_sign_of_j2():
    """0=права (J2>=0), 1=левая (J2<=0) — бриф T2.K; на несингулярной позе знаки противоположны."""
    model = _make_scara()
    pose = (300.0, -210.0, -40.0, -100.0)  # r=366.19мм — вдали от границ досягаемости
    j_right = model.ik(pose, 0)
    j_left = model.ik(pose, 1)
    assert j_right is not None and j_left is not None
    assert j_right[1] >= 0.0, j_right
    assert j_left[1] <= 0.0, j_left
    assert j_right[1] == pytest.approx(-j_left[1], abs=TOL)
    for joints in (j_right, j_left):
        got = model.fk(joints)
        for expected, actual in zip(pose, got):
            assert actual == pytest.approx(expected, abs=TOL)


def test_unreachable_returns_none():
    """r > l1+l2 (700 > 600) и r < |l1-l2| (20 < 50) -> None для обеих рук (бриф T2.K, приёмка п.3)."""
    model = _make_scara()
    too_far = (700.0, 0.0, -40.0, 0.0)
    too_close = (20.0, 0.0, -40.0, 0.0)
    for pose in (too_far, too_close):
        for hand in (0, 1):
            assert model.ik(pose, hand) is None, (pose, hand)


def test_fully_stretched_boundary():
    """r == l1+l2 (600.0, включительно) — рука вытянута, J2==0 для ОБЕИХ рук (нет ±ambiguity)."""
    model = _make_scara()
    pose = (600.0, 0.0, -40.0, 0.0)
    for hand in (0, 1):
        joints = model.ik(pose, hand)
        assert joints is not None, hand
        assert joints[1] == pytest.approx(0.0, abs=TOL), (hand, joints)
        got = model.fk(joints)
        for expected, actual in zip(pose, got):
            assert actual == pytest.approx(expected, abs=TOL)


def test_chain_points_base_elbow_tool():
    """chain_points начинается в (0,0,·), плечо на расстоянии l1 от оси, конец — XY позы fk (бриф T2.K).

    Контракт скорректирован ревью T2.K (2026-09-27, решение ведущего): `chain_points`
    возвращает `list[Chain]` — список ломаных, одна на кинематическую цепь (дельта даст
    три), а не плоский список точек (для SCARA, последовательной цепи, ровно ОДНА
    ломаная). Индексация `[0]` — единственная правка этого теста ревью T2.K, остальные
    проверки не тронуты."""
    model = _make_scara()
    joints = (30.0, 45.0, -75.0, 10.0)  # J1,J2,Z,J4 — произвольная несингулярная поза
    chains = model.chain_points(joints)
    assert len(chains) == 1, chains  # SCARA — одна последовательная цепь
    points = chains[0]
    assert len(points) == 3, points
    base, elbow, tool = points
    assert base[0] == pytest.approx(0.0, abs=TOL)
    assert base[1] == pytest.approx(0.0, abs=TOL)
    elbow_r = math.hypot(elbow[0], elbow[1])
    assert elbow_r == pytest.approx(L1, abs=TOL), elbow
    fk_pose = model.fk(joints)
    assert tool[0] == pytest.approx(fk_pose[0], abs=TOL)
    assert tool[1] == pytest.approx(fk_pose[1], abs=TOL)


def test_zone_checks_delegate_to_geometry():
    """model.check_point/check_segment == programs/geometry.check_point/check_segment (делегирование,
    И6 брифа: "вторая правда о досягаемости не заводится"). Workspace — боевые дефолты params_v2 через
    to_eng (не литералы). Включает случай отрезка через мёртвую зону -> R_DEAD_ZONE."""
    from Services.robot_comm.kinematics import ScaraModel

    ws_names = (
        "P_WS_R_MIN",
        "P_WS_R_MAX",
        "P_WS_Z_MIN",
        "P_WS_Z_MAX",
        "P_WS_RZ_MIN",
        "P_WS_RZ_MAX",
        "P_WS_ANG_MIN",
        "P_WS_ANG_MAX",
        "P_WS_BOX_EN",
        "P_WS_X_MIN",
        "P_WS_X_MAX",
        "P_WS_Y_MIN",
        "P_WS_Y_MAX",
    )
    eng = {name: to_eng(name, PARAMS[PARAM_ID[name]]["default"]) for name in ws_names}
    ws = Workspace.from_params(eng)
    model = ScaraModel(l1=L1, l2=L2)

    ok_pose = (300.0, 0.0, -75.0, 0.0)
    bad_pose = (50.0, 0.0, -75.0, 0.0)  # r=50 < r_min=100 по умолчанию
    assert check_point(ws, *ok_pose) == 0, "самопроверка оракула"
    assert check_point(ws, *bad_pose) == REASON["R_OUT_OF_ZONE"], "самопроверка оракула"
    assert model.check_point(ws, ok_pose) == check_point(ws, *ok_pose)
    assert model.check_point(ws, bad_pose) == check_point(ws, *bad_pose)

    # A(angle=-85°,r≈150), B(angle=+85°,r≈150) — оба индивидуально валидны, отрезок A->B проходит
    # через мёртвую зону (ближайшая к (0,0) точка отрезка ~13.1мм < r_min=100мм), см. тот же случай
    # в raw-виде в test_sim_v2_motion.py::test_dead_zone_segment_line_rejected (131,-1494)/(131,1494).
    p0 = (13.1, -149.4, -75.0, 0.0)
    p1 = (13.1, 149.4, -75.0, 0.0)
    oracle_segment = check_segment(ws, p0[0], p0[1], p1[0], p1[1])
    assert oracle_segment == REASON["R_DEAD_ZONE"], "самопроверка оракула"
    assert model.check_segment(ws, p0, p1) == oracle_segment


def test_make_model_known_and_unknown():
    """make_model({"type":"scara",...}) строит ScaraModel с заданными l1/l2; неизвестный type -> ValueError
    со списком известных типов (бриф T2.K), сообщение содержит "scara"."""
    from Services.robot_comm.kinematics import make_model

    model = make_model({"type": "scara", "l1": 300.0, "l2": 250.0})
    # l1/l2 не названы публичным атрибутом в брифе -> проверяем через fk/chain_points,
    # не угадывая имя поля.
    stretched = model.fk((0.0, 0.0, 0.0, 0.0))  # J1=J2=0 -> вытянута вдоль X на l1+l2
    assert stretched[0] == pytest.approx(550.0, abs=TOL)
    assert stretched[1] == pytest.approx(0.0, abs=TOL)
    elbow = model.chain_points((0.0, 0.0, 0.0, 0.0))[0][
        1
    ]  # [0] — правка ревью T2.K (см. test_chain_points_base_elbow_tool)
    assert math.hypot(elbow[0], elbow[1]) == pytest.approx(300.0, abs=TOL)

    with pytest.raises(ValueError, match="scara"):
        make_model({"type": "unknown_robot_type"})


# =========================================================================== #
# RobotSimCoreV2 через модель
# =========================================================================== #


def test_sim_default_model_is_scara():
    """RobotSimCoreV2() без model= -> модель по умолчанию — ScaraModel (бриф T2.K)."""
    from Services.robot_comm.kinematics import ScaraModel

    core = RobotSimCoreV2()
    assert isinstance(core.model, ScaraModel)


class _AlwaysOutOfZoneModel:
    """Duck-typed подставная модель — только check_point нужен: JOINT и HOME в _check_motion
    не вызывают check_segment (только LINE), см. sim_core_v2._check_motion."""

    def check_point(self, ws, pose):
        return REASON["R_OUT_OF_ZONE"]


def test_sim_zone_goes_through_model():
    """Подставная модель, запрещающая всё, -> валидный PTP_MOVE JOINT и HOME отвечают NAK E_RANGE
    (бриф T2.K, приёмка: "проверка идёт через модель, а не мимо неё")."""
    core = RobotSimCoreV2(model=_AlwaysOutOfZoneModel())
    servo_on(core, 1)

    res_joint = cmd(core, 2, OP["PTP_MOVE"], mm(300.0), mm(0.0), mm(-75.0), mm(0.0), KIND["JOINT"], 100)
    assert res_joint["status"] == NAK
    assert res_joint["errno"] == ERR["E_RANGE"]
    assert res_joint["rvals"][0] == REASON["R_OUT_OF_ZONE"]

    hx, hy, hz, hrz = home_target()
    res_home = cmd(core, 3, OP["HOME"], 100)
    assert res_home["status"] == NAK
    assert res_home["errno"] == ERR["E_RANGE"]
    assert res_home["rvals"][0] == REASON["R_OUT_OF_ZONE"]


def test_sim_joints_match_home_ik():
    """core.joints() (новый метод) == core.model.ik(поза из TLM_X/Y/Z/RZ, TLM_HAND), после boot
    поза = боевой P_HOME_*/P_HAND (бриф T2.K: "joints() — суставы текущей позы... для окна-вида")."""
    core = RobotSimCoreV2()
    p_hand = PARAMS[PARAM_ID["P_HAND"]]["default"]
    home_pose = (
        to_eng("P_HOME_X", PARAMS[PARAM_ID["P_HOME_X"]]["default"]),
        to_eng("P_HOME_Y", PARAMS[PARAM_ID["P_HOME_Y"]]["default"]),
        to_eng("P_HOME_Z", PARAMS[PARAM_ID["P_HOME_Z"]]["default"]),
        to_eng("P_HOME_RZ", PARAMS[PARAM_ID["P_HOME_RZ"]]["default"]),
    )
    expected = core.model.ik(home_pose, p_hand)
    assert expected is not None, "боевой дом обязан быть достижим ik-моделью по умолчанию"

    got = core.joints()
    assert got is not None
    for exp_val, got_val in zip(expected, got):
        assert got_val == pytest.approx(exp_val, abs=0.1)
