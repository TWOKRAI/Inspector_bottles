"""Независимые приёмочные тесты T2.J — JOINT/HOME интерполируют по суставам через
модель робота, а не по прямой в Cartesian (`plans/robot-protocol-v2/tasks.md`, брифинг
«T2.J — JOINT по суставам»), написаны ДО реализации по DESIGN из брифинга ведущего.

Источник истины — DESIGN из брифинга (типизирован ниже дословно), НЕ сам симулятор
(`sim_core_v2.py` уже существует после T2.K и интерполирует JOINT/HOME по прямой в
Cartesian — известный баг, который T2.J чинит). DESIGN:

  - После T2.J: JOINT и HOME интерполируют суставы линейно от `model.ik(start pose,
    TLM_HAND)` к `model.ik(target, P_HAND)`. Поза каждого тика = `model.fk(joints)`.
    J1 из `ik` лежит в `(-180, 180]`, поэтому путь никогда не пересекает ±180.
  - Тайминг не меняется: ход по-прежнему длится `path_len / speed`, `path_len =
    max(Cartesian XYZ-дистанция, |ΔRZ|)`, шаг/тик `min(speed*dt, MAX_STEP_MM)` — число
    тиков совпадает с T2.2-счётом ±1. Финальная поза = цель (регистры хранят 0.1 мм).
  - Если `model.ik` вернул `None` для старта или цели — ход падает обратно на прямую
    в Cartesian.
  - LINE и JOG_STEP/JOG_CONT остаются прямой в Cartesian — без изменений.

Сценарий пересечения запретного сектора (боевые дефолты, сектор J1 ±165°) —
дословно из брифинга: `(-250, 350) -> (-450, -150)`. Независимо пересчитан этим
тестером через `ScaraModel()` (l1=325, l2=275 — те же дефолты, что и в
`RobotSimCoreV2()` без `model=`) ДО написания тестов: прямая в Cartesian между этими
точками выходит за угловой сектор на f≈0.52..1.0 (angle до ~172° при r до ~600),
суставная интерполяция через `ik`/`fk` — не выходит ни разу на сетке 101 точки, при
этом отклоняется от хорды на максимум ≈814 мм (см. отчёт, разница в J1 объясняется:
`ik` не разворачивает J1 через ±180, поэтому суставная интерполяция идёт «длинным»
путём через ноль, а не «коротким» через разрыв — этим и объясняется, почему прямая в
Cartesian ломает сектор, а суставный путь — нет).

ЗАПРЕЩЕНО трогать (не открывать, не grep'ать, не импортировать):
`Services/robot_comm/server/sim_core_v2.py` (кроме уже читанного как read-only
reference по брифингу — реализация ЕЩЁ НЕ существует в этом ворктри, T2.J ещё не
влит), diff/файлы разработчика, `.claude/worktrees/team-t2j-dev*` и любые другие
воркtree команды. Ворктри этого тестера стоит на коммите ДО T2.J (6bec0ae1) —
слепота обеспечена деревом, не только этим абзацем.

Регистр-помощники (u16/mm/s16/cmd/read_res/home_target/fresh_core/servo_on/
move_to_via_joint/run_until_activity_zero/DEFAULT_WS) — скопированы по паттерну
`test_sim_v2_motion.py` (файл вне FILES этого таска, не импортируется).
"""

from __future__ import annotations

import math

import pytest

from Services.robot_comm.core.params_v2 import PARAM_ID, PARAMS
from Services.robot_comm.core.protocol_v2 import KIND, OP, REG, REG_COUNT
from Services.robot_comm.kinematics import ScaraModel
from Services.robot_comm.programs.geometry import Workspace, check_point
from Services.robot_comm.server.sim_core_v2 import REG_SPACE_SIZE_V2, RobotSimCoreV2

ACK = 1
NAK = 2
FW_BUILD = 7
TICK_S = 0.01
MAX_STEP = 100.0 / 3.0

# --------------------------------------------------------------------------- #
# Регистр-помощники (паттерн test_sim_v2_motion.py, скопирован не импортирован)
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


def move_to_via_joint(core, seq: int, x: int, y: int, z: int, rz: int, spd: int = 100) -> dict:
    """JOINT-переезд до полной остановки — контролируемая установка стартовой позы."""
    res = cmd(core, seq, OP["PTP_MOVE"], x, y, z, rz, KIND["JOINT"], spd)
    assert res["status"] == ACK, f"предусловие: JOINT в ({x},{y},{z},{rz}) должен приниматься: {res}"
    run_until_activity_zero(core)
    return res


def run_until_activity_zero(core, max_ticks: int = 5000) -> int:
    for i in range(max_ticks):
        if core.read(REG["TLM_ACTIVITY"], 1)[0] == 0:
            return i
        core.tick()
    pytest.fail(f"команда всё ещё активна после {max_ticks} тиков — цикл не должен зависать")


def pose_eng(core) -> tuple[float, float, float, float]:
    """Поза из регистров в инженерных единицах — публичная поверхность (`regs`+`REG`),
    без обращения к приватным методам core (вне FILES этого таска)."""
    return (
        s16(core.regs[REG["TLM_X"]]) / 10.0,
        s16(core.regs[REG["TLM_Y"]]) / 10.0,
        s16(core.regs[REG["TLM_Z"]]) / 10.0,
        s16(core.regs[REG["TLM_RZ"]]) / 10.0,
    )


def chord_perp_dist_xy(x0: float, y0: float, x1: float, y1: float, x: float, y: float) -> float:
    """Перпендикулярное расстояние (x,y) от отрезка (x0,y0)-(x1,y1) — тестовая утилита
    (измеряет кривизну пути), не копия производственной геометрии зоны."""
    dx, dy = x1 - x0, y1 - y0
    len2 = dx * dx + dy * dy
    if len2 == 0.0:
        return math.hypot(x - x0, y - y0)
    t = ((x - x0) * dx + (y - y0) * dy) / len2
    px, py = x0 + t * dx, y0 + t * dy
    return math.hypot(x - px, y - py)


def track_pose_until_done(core, max_ticks: int = 300) -> list[tuple[float, float, float, float]]:
    """Тикает до TLM_ACTIVITY==0, возвращает позу ПОСЛЕ каждого тика (включая первый —
    ACK-тик уже сделал шаг по контракту motion-модели)."""
    poses = []
    for _ in range(max_ticks):
        if core.read(REG["TLM_ACTIVITY"], 1)[0] == 0:
            return poses
        core.tick(TICK_S)
        poses.append(pose_eng(core))
    pytest.fail(f"команда всё ещё активна после {max_ticks} тиков — цикл не должен зависать")


# Дефолтная рабочая зона (боевые дефолты P_WS_*, сверено с params_v2.PARAMS —
# идентична DEFAULT_WS в test_sim_v2_motion.py).
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

# Сценарий пересечения сектора из брифинга (дословно) — старт/цель в мм.
CROSS_START = (-250.0, 350.0, -75.0, 0.0)
CROSS_TARGET = (-450.0, -150.0, -75.0, 0.0)


def _assert_straight_chord_leaves_zone(p0: tuple[float, ...], p1: tuple[float, ...]) -> None:
    """Доказательство предпосылки: линейная (Cartesian) хорда p0->p1 обязана хотя бы
    раз нарушить check_point на боевых дефолтах зоны — иначе сценарий не годится как
    репродукция бага T2.J (независимая проверка оракулом geometry.check_point,
    НИЧЕГО из sim_core_v2 не задействовано)."""
    hits = 0
    for i in range(101):
        f = i / 100.0
        p = tuple(a + f * (b - a) for a, b in zip(p0, p1))
        if check_point(DEFAULT_WS, *p) != 0:
            hits += 1
    assert hits > 0, f"предпосылка теста не выполняется: прямая {p0}->{p1} ни разу не покидает зону"


# =========================================================================== #
# RED — суставная интерполяция удерживает JOINT/HOME внутри зоны
# =========================================================================== #


def test_joint_move_never_leaves_zone():
    """Каждый тик JOINT-хода (-250,350)->(-450,-150) (боевые дефолты, брифинг T2.J)
    обязан проходить check_point — сегодня симулятор ведёт JOINT по прямой в
    Cartesian и эту прямую (доказано ниже) уносит за угловой сектор [-165,165]."""
    _assert_straight_chord_leaves_zone(CROSS_START, CROSS_TARGET)

    core = fresh_core()
    servo_on(core, 1)
    move_to_via_joint(core, 2, mm(CROSS_START[0]), mm(CROSS_START[1]), mm(CROSS_START[2]), mm(CROSS_START[3]))
    assert pose_eng(core) == pytest.approx(CROSS_START, abs=0.1)

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
    samples = [pose_eng(core)]  # поза сразу после ACK-тика — уже первый шаг хода
    samples += track_pose_until_done(core)

    assert len(samples) >= 3, "ход должен занять несколько тиков (MAX_STEP_MM), иначе тест ничего не проверяет"
    violations = [(x, y, z, rz) for (x, y, z, rz) in samples if check_point(DEFAULT_WS, x, y, z, rz) != 0]
    assert violations == [], f"суставный путь обязан оставаться в зоне на каждом тике, нарушения: {violations[:3]}"
    assert pose_eng(core) == pytest.approx(CROSS_TARGET, abs=0.1)


def test_joint_path_is_curved_not_chord():
    """Путь JOINT-хода (-250,350)->(-450,-150) обязан заметно (>20мм) отклоняться от
    прямой хорды start->target — сегодня симулятор ведёт JOINT РОВНО по хорде
    (отклонение ~0), после T2.J путь идёт по суставам (независимо пересчитано через
    ScaraModel до написания теста: реальное отклонение доходит до ≈814мм)."""
    core = fresh_core()
    servo_on(core, 1)
    move_to_via_joint(core, 2, mm(CROSS_START[0]), mm(CROSS_START[1]), mm(CROSS_START[2]), mm(CROSS_START[3]))
    start = pose_eng(core)

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
    samples = [pose_eng(core)]
    samples += track_pose_until_done(core)

    max_dev = max(
        chord_perp_dist_xy(start[0], start[1], CROSS_TARGET[0], CROSS_TARGET[1], x, y) for x, y, _z, _rz in samples
    )
    assert max_dev > 20.0, (
        f"путь должен заметно отклоняться от хорды (суставная интерполяция), получено {max_dev:.2f}мм"
    )


def test_home_uses_joint_path():
    """HOME из (-250,350) обязан идти по суставам, не по прямой в Cartesian: прямая
    (доказано ниже независимым оракулом) ныряет ближе r_min (=100мм) к оси J1 —
    суставный путь остаётся в зоне на каждом тике."""
    # ЮНИТ-БАГ тестера (найден разработчиком T2.J): home_target() отдаёт СЫРЫЕ ×10
    # регистровые значения (как аргументы команд), а не инженерные мм/град — здесь
    # нужна eng-поза для сравнения с pose_eng(); тот же /10.0, что и в соседних
    # тестах этого файла (test_ik_none_falls_back_to_straight_line и др.). Без
    # конверсии assert ниже сравнивал 300.0 (реальная поза) с 3000.0±0.1 — не
    # дефект симулятора, чистая ошибка масштаба в тесте.
    home = tuple(v / 10.0 for v in home_target())
    _assert_straight_chord_leaves_zone(CROSS_START, home)

    core = fresh_core()
    servo_on(core, 1)
    move_to_via_joint(core, 2, mm(CROSS_START[0]), mm(CROSS_START[1]), mm(CROSS_START[2]), mm(CROSS_START[3]))
    assert pose_eng(core) == pytest.approx(CROSS_START, abs=0.1)

    res = cmd(core, 3, OP["HOME"], 100)
    assert res["status"] == ACK, res
    samples = [pose_eng(core)]
    samples += track_pose_until_done(core)

    assert len(samples) >= 3
    violations = [(x, y, z, rz) for (x, y, z, rz) in samples if check_point(DEFAULT_WS, x, y, z, rz) != 0]
    assert violations == [], f"HOME по суставам обязан оставаться в зоне на каждом тике, нарушения: {violations[:3]}"
    assert pose_eng(core) == pytest.approx(home, abs=0.1)


# =========================================================================== #
# guard — тайминг и финальная поза не меняются T2.J (регрессия к T2.2-контракту)
# =========================================================================== #


def test_joint_ticks_match_timing_contract():
    """guard: число тиков JOINT-хода не меняется T2.J — тайминг остаётся
    path_len/speed с тем же MAX_STEP_MM/TICK_INTERVAL_S потолком (брифинг T2.J,
    «Timing is unchanged»). Ожидается GREEN уже сегодня (симулятор до T2.J считает
    тайминг по той же формуле, просто по прямой) — регрессионный якорь."""
    core = fresh_core()
    servo_on(core, 1)
    move_to_via_joint(core, 2, mm(CROSS_START[0]), mm(CROSS_START[1]), mm(CROSS_START[2]), mm(CROSS_START[3]))

    dx = CROSS_TARGET[0] - CROSS_START[0]
    dy = CROSS_TARGET[1] - CROSS_START[1]
    dz = CROSS_TARGET[2] - CROSS_START[2]
    drz = abs(CROSS_TARGET[3] - CROSS_START[3])
    path_len = max(math.sqrt(dx * dx + dy * dy + dz * dz), drz)

    spd_l = PARAMS[PARAM_ID["P_SPD_L"]]["default"]
    pct = PARAMS[PARAM_ID["P_SPD_DEFAULT"]]["default"]
    v = spd_l * pct / 100.0
    step = min(v * TICK_S, MAX_STEP)
    expected_extra = math.ceil(path_len / step) - 1

    res = cmd(
        core,
        3,
        OP["PTP_MOVE"],
        mm(CROSS_TARGET[0]),
        mm(CROSS_TARGET[1]),
        mm(CROSS_TARGET[2]),
        mm(CROSS_TARGET[3]),
        KIND["JOINT"],
        0,  # 0 -> P_SPD_DEFAULT
    )
    assert res["status"] == ACK, res
    actual_extra = run_until_activity_zero(core, max_ticks=500)
    assert abs(actual_extra - expected_extra) <= 1, (
        f"ожидалось {expected_extra} доп.тиков (±1), получено {actual_extra} (path_len={path_len:.3f}, v={v})"
    )


def test_joint_final_pose_equals_target():
    """guard: JOINT-ход обязан прибыть в цель ровно (регистры хранят 0.1мм) — не
    меняется T2.J. Ожидается GREEN уже сегодня."""
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
    track_pose_until_done(core)
    assert s16(core.read(REG["TLM_X"], 1)[0]) == mm(CROSS_TARGET[0])
    assert s16(core.read(REG["TLM_Y"], 1)[0]) == mm(CROSS_TARGET[1])
    assert s16(core.read(REG["TLM_Z"], 1)[0]) == mm(CROSS_TARGET[2])
    assert s16(core.read(REG["TLM_RZ"], 1)[0]) == mm(CROSS_TARGET[3])
    assert core.read(REG["TLM_DONE_SEQ"], 1)[0] == res["seq"]


def test_joint_rz_reaches_target_exactly_and_monotonic():
    """guard: RZ = J1+J2+J4 — сумма трёх линейно интерполируемых суставов ОСТАЁТСЯ
    аффинной функцией прогресса хода (как и сегодняшняя прямая в Cartesian, которая
    тоже линейно интерполирует RZ) — монотонность и точное прибытие не меняются T2.J.
    Ожидается GREEN уже сегодня — регрессионный якорь, не новое поведение."""
    core = fresh_core()
    servo_on(core, 1)
    hx, hy, hz, hrz = home_target()
    target_rz = hrz + 500  # +50.0° по RZ, xy/z не меняются — изолирует RZ
    res = cmd(core, 2, OP["PTP_MOVE"], hx, hy, hz, target_rz, KIND["JOINT"], 100)
    assert res["status"] == ACK, res

    prev_rz = s16(core.read(REG["TLM_RZ"], 1)[0])
    assert hrz <= prev_rz <= target_rz  # ACK-тик уже сделал первый шаг
    ticks = 0
    while core.read(REG["TLM_ACTIVITY"], 1)[0] != 0 and ticks < 300:
        core.tick(TICK_S)
        ticks += 1
        cur_rz = s16(core.read(REG["TLM_RZ"], 1)[0])
        assert prev_rz <= cur_rz <= target_rz, "RZ должен монотонно приближаться к цели, не перелетая"
        prev_rz = cur_rz
    assert s16(core.read(REG["TLM_RZ"], 1)[0]) == target_rz


# =========================================================================== #
# guard — фолбэк на прямую при model.ik()->None, LINE не меняется
# =========================================================================== #


class _NeverIkModel:
    """Делегирует всё в реальную ScaraModel, кроме `ik` — всегда `None` (симулирует
    модель, для которой старт/цель ход вне досягаемости). Проверяет фолбэк T2.J на
    прямую в Cartesian (брифинг: «If model.ik returns None ... falls back»)."""

    def __init__(self) -> None:
        self._real = ScaraModel()
        self.kind = self._real.kind
        self.axes = self._real.axes
        self.joint_names = self._real.joint_names

    def fk(self, joints):
        return self._real.fk(joints)

    def ik(self, pose, hand):
        return None

    def chain_points(self, joints):
        return self._real.chain_points(joints)

    def check_point(self, ws, pose):
        return self._real.check_point(ws, pose)

    def check_segment(self, ws, p0, p1):
        return self._real.check_segment(ws, p0, p1)


def test_ik_none_falls_back_to_straight_line():
    """guard: с моделью, у которой `ik` всегда None, JOINT-ход обязан остаться
    коллинеарным хорде start->target (в пределах 0.2мм — округление регистров до
    0.1мм на КАЖДОМ конце отрезка даёт до ~0.14мм геометрической ошибки внутри).
    Сегодняшний симулятор ведёт JOINT по прямой БЕЗ обращения к model.ik вообще —
    та же самая прямая, поэтому тест ожидается GREEN уже сейчас."""
    core = RobotSimCoreV2(model=_NeverIkModel())
    servo_on(core, 1)
    hx, hy, hz, hrz = home_target()
    tx, ty, tz, trz = hx + 1500, hy, hz, hrz  # 150мм по X, в зоне (см. test_sim_v2_motion.py)
    start = pose_eng(core)
    target = (tx / 10.0, ty / 10.0, tz / 10.0, trz / 10.0)

    res = cmd(core, 2, OP["PTP_MOVE"], tx, ty, tz, trz, KIND["JOINT"], 100)
    assert res["status"] == ACK, res
    samples = [pose_eng(core)]
    samples += track_pose_until_done(core)

    for x, y, _z, _rz in samples:
        dev = chord_perp_dist_xy(start[0], start[1], target[0], target[1], x, y)
        assert dev <= 0.2, f"фолбэк обязан идти по прямой, получено отклонение {dev:.4f}мм в точке ({x},{y})"


def test_line_move_stays_straight():
    """guard: LINE не меняется T2.J — путь обязан остаться коллинеарным хорде.
    Ожидается GREEN уже сегодня (LINE и до T2.J интерполируется по прямой)."""
    core = fresh_core()
    servo_on(core, 1)
    hx, hy, hz, hrz = home_target()
    tx, ty, tz, trz = hx + 1000, hy, hz, hrz  # 100мм по X — см. test_ptp_line_monotonic...
    start = pose_eng(core)
    target = (tx / 10.0, ty / 10.0, tz / 10.0, trz / 10.0)

    res = cmd(core, 2, OP["PTP_MOVE"], tx, ty, tz, trz, KIND["LINE"], 100)
    assert res["status"] == ACK, res
    samples = [pose_eng(core)]
    samples += track_pose_until_done(core)

    for x, y, _z, _rz in samples:
        dev = chord_perp_dist_xy(start[0], start[1], target[0], target[1], x, y)
        assert dev <= 0.2, f"LINE обязан идти по прямой, получено отклонение {dev:.4f}мм в точке ({x},{y})"


# =========================================================================== #
# guard — смена руки во время JOINT: остаётся в зоне, физически применяется в конце
# =========================================================================== #


def test_hand_change_during_joint():
    """guard: PARAM_SET P_HAND на другую руку, затем JOINT — все тики в зоне, ход
    прибывает, TLM_HAND становится новой рукой. Малый ход около дома (боевые
    дефолты) выбран НАРОЧНО скромным: независимая проверка (ScaraModel, до написания
    теста) показала, что для сценария пересечения сектора из брифинга (-250,350)->
    (-450,-150) смена руки даёт суставный путь, который САМ выходит за r_max (~600мм)
    — не годится как чистая регрессия TLM_HAND, см. «что я оставил открытым» в
    отчёте. Малый ход в зоне у обеих рук уже сегодня валиден (прямая в Cartesian на
    50мм не пересекает сектор) — GREEN уже сейчас, регрессионный якорь на смену руки."""
    core = fresh_core()
    servo_on(core, 1)
    p_hand_default = PARAMS[PARAM_ID["P_HAND"]]["default"]
    assert core.read(REG["TLM_HAND"], 1)[0] == p_hand_default
    new_hand = 0 if p_hand_default == 1 else 1

    res_set = cmd(core, 2, OP["PARAM_SET"], PARAM_ID["P_HAND"], u16(new_hand))
    assert res_set["status"] == ACK, res_set
    assert core.read(REG["TLM_HAND"], 1)[0] == p_hand_default  # ещё не применено физически

    hx, hy, hz, hrz = home_target()
    tx, ty, tz, trz = hx + 500, hy, hz, hrz  # +50мм по X — скромный ход, см. докстринг

    res = cmd(core, 3, OP["PTP_MOVE"], tx, ty, tz, trz, KIND["JOINT"], 100)
    assert res["status"] == ACK, res
    samples = [pose_eng(core)]
    samples += track_pose_until_done(core)

    violations = [(x, y, z, rz) for (x, y, z, rz) in samples if check_point(DEFAULT_WS, x, y, z, rz) != 0]
    assert violations == [], f"нарушения зоны во время смены руки: {violations[:3]}"
    assert core.read(REG["TLM_X"], 1)[0] == tx
    assert core.read(REG["TLM_HAND"], 1)[0] == new_hand
