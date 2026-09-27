"""Независимые приёмочные тесты симулятора v2 (T2.2 — motion/zone/stop/FAULT),
написанные ДО реализации по контракту `t2.2-contract.md` (в корне ворктри).

Источник истины — t2.2-contract.md, а не сам симулятор (`sim_core_v2.py` уже
существует после T2.1, но содержит только заглушку PTP и HOME/JOG_*/CVT_JOB/
SC_RUN как E_INTERNAL — см. `test_unimplemented_opcodes_are_internal_error` и
`test_ptp_move_completes_within_500_ticks_at_target_pose` в
`test_sim_v2_core.py`, файл прочитан ТОЛЬКО за паттерном mailbox-хелперов,
поведение симулятора из него не выводилось).

Адреса/опкоды/errno/reasons/param id — импортированы по имени из
`protocol_v2`/`params_v2`. Числа, которые контракт называет явно (TICK 0.01,
ACK/NAK), — литералы, как и в T2.1. Геометрия зоны — из уже принятого
`programs/geometry.py` (используется и как SUT-независимый оракул для
`check_point`, и как источник дефолтов зоны).

ЗАПРЕЩЕНО трогать (не открывать, не grep'ать, не импортировать):
`Services/robot_comm/server/sim_core_v2.py`,
`Services/robot_comm/tests/test_sim_v2_core_internal.py`,
любой `.claude/worktrees/rpv2-t2.2-dev*`.
Ничего из перечисленного в ходе работы не открывалось.

RED на базе ожидается почти по всему файлу: PTP всё ещё телепортируется через
4 тика (заглушка T2.1), HOME/JOG_* отвечают E_INTERNAL, `TICK_INTERVAL_S` /
`MAX_STEP_MM` / `vfd_stop_requests` / `inject_motion_fault` ещё не существуют.
Эти четыре символа НЕ импортируются на уровне модуля (иначе один
ImportError убил бы весь файл) — обращение к ним лениво, внутри тестов
(`sim_core_v2.TICK_INTERVAL_S`, `core.vfd_stop_requests`,
`core.inject_motion_fault()`), так что падает только тест, которому они
нужны, с AttributeError.
"""

from __future__ import annotations

import math

import pytest

from Services.robot_comm.core.params_v2 import PARAM_ID, PARAMS
from Services.robot_comm.core.protocol_v2 import ERR, KIND, OP, REASON, REG, REG_COUNT, STOP_LEVEL
from Services.robot_comm.programs.geometry import Workspace, check_point

# модуль импортируется целиком (безопасно — существует с T2.1); новые для
# T2.2 имена (TICK_INTERVAL_S, MAX_STEP_MM) читаются лениво внутри тестов
from Services.robot_comm.kinematics import make_model
from Services.robot_comm.server import sim_core_v2
from Services.robot_comm.server.sim_core_v2 import REG_SPACE_SIZE_V2, RobotSimCoreV2

# T2.J2 (расширение FILES ведущим 2026-09-27): эти тесты проверяют зону P_WS
# (рабочую зону прошивки), а не пределы суставов модели — точки специально взяты
# у границы кольца/сектора, где |J1| естественно превышает дефолтный предел ±132
# ScaraModel (заглушка GATE-1, plans/robot-protocol-v2 §9 q1). Модель без пределов
# суставов изолирует «эта проверка идёт через зону, а не через новый предел».
_NO_JOINT_LIMITS = make_model({"type": "scara", "joint_limits": [None, None, None, None]})

# ACK/NAK контракт называет числом (как в T2.1-контракте) -> литерал, не импорт
ACK = 1
NAK = 2

FW_BUILD = 7

# TICK_INTERVAL_S/MAX_STEP_MM контракт тоже называет числом явно — литералы
# для арифметики тестов; отдельные тесты ниже проверяют, что реализация
# отдаёт РОВНО эти значения через sim_core_v2.TICK_INTERVAL_S/MAX_STEP_MM.
TICK_S = 0.01
MAX_STEP = 100.0 / 3.0


# --------------------------------------------------------------------------- #
# Регистр-помощники — идентичны паттерну T2.1 (test_sim_v2_core.py), скопированы,
# а не импортированы (файл вне FILES этого таска).
# --------------------------------------------------------------------------- #


def u16(value: int) -> int:
    return value & 0xFFFF


def mm(eng: float) -> int:
    """Инженерное значение (мм или °) -> сырой регистр ×0.1, округление до целого."""
    return round(eng * 10)


class RecordingRegs(list):
    """list, фиксирующий каждый __setitem__ (индекс или слайс) для теста И5."""

    def __init__(self, *args):
        super().__init__(*args)
        self.write_log: list[int] = []

    def __setitem__(self, key, value):
        if isinstance(key, slice):
            self.write_log.extend(range(*key.indices(len(self))))
        else:
            idx = key + len(self) if key < 0 else key
            self.write_log.append(idx)
        super().__setitem__(key, value)


def last_pos(log: list[int], addr: int) -> int:
    positions = [i for i, a in enumerate(log) if a == addr]
    assert positions, f"адрес {addr:#06x} ни разу не записан в этом логе"
    return positions[-1]


def first_pos(log: list[int], addr: int) -> int:
    assert addr in log, f"адрес {addr:#06x} ни разу не записан в этом логе"
    return log.index(addr)


def cmd(core, seq: int, opcode: int, *args: int, argc: int | None = None) -> dict:
    core.write(REG["CMD_SEQ"], [u16(seq)])
    core.write(REG["CMD_OPCODE"], [opcode])
    n = len(args) if argc is None else argc
    core.write(REG["CMD_ARGC"], [n])
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


def s16(raw: int) -> int:
    """u16 регистра -> знаковое значение (two's complement)."""
    return raw - 65536 if raw >= 0x8000 else raw


def pose(core) -> tuple[int, int, int, int]:
    # Правка ведущего (T2.2): регистры позы хранят u16, цели — со знаком; без
    # декодирования отрицательные Y/Z/RZ дома (-2100/-400/-1000) не сравнимы.
    return (
        s16(core.read(REG["TLM_X"], 1)[0]),
        s16(core.read(REG["TLM_Y"], 1)[0]),
        s16(core.read(REG["TLM_Z"], 1)[0]),
        s16(core.read(REG["TLM_RZ"], 1)[0]),
    )


def home_target() -> tuple[int, int, int, int]:
    x = PARAMS[PARAM_ID["P_HOME_X"]]["default"]
    y = PARAMS[PARAM_ID["P_HOME_Y"]]["default"]
    z = PARAMS[PARAM_ID["P_HOME_Z"]]["default"]
    rz = PARAMS[PARAM_ID["P_HOME_RZ"]]["default"]
    return x, y, z, rz


def fresh_core(**kw) -> RobotSimCoreV2:
    return RobotSimCoreV2(fw_build=FW_BUILD, **kw)


def recording_core() -> RobotSimCoreV2:
    regs = RecordingRegs([0] * REG_SPACE_SIZE_V2)
    return RobotSimCoreV2(regs=regs, fw_build=FW_BUILD)


def run_until_activity_zero(core, max_ticks: int = 5000) -> int:
    """Тикает, пока TLM_ACTIVITY не станет 0. Жёсткий потолок — тест падает
    с сообщением, а не виснет (правило DESIGN)."""
    for i in range(max_ticks):
        if core.read(REG["TLM_ACTIVITY"], 1)[0] == 0:
            return i
        core.tick()
    pytest.fail(f"команда всё ещё активна после {max_ticks} тиков — цикл не должен зависать")


def servo_on(core, seq: int = 1) -> None:
    res = cmd(core, seq, OP["SERVO"], 1)
    assert res["status"] == ACK, "предусловие: серво должно включаться"


def move_to_via_joint(core, seq: int, x: int, y: int, z: int, rz: int, spd: int = 100) -> dict:
    """JOINT-переезд (обходит hand/segment) до полной остановки — контролируемая
    установка текущей позы перед LINE/JOG-тестами."""
    res = cmd(core, seq, OP["PTP_MOVE"], x, y, z, rz, KIND["JOINT"], spd)
    assert res["status"] == ACK, f"предусловие: JOINT в ({x},{y},{z},{rz}) должен приниматься: {res}"
    run_until_activity_zero(core)
    return res


def set_idle_param(core, seq: int, name: str, raw_value: int) -> dict:
    """PARAM_SET параметра apply=idle на простаивающем sim — по T2.1-паттерну
    busy-семантики применяется сразу, без отдельного PARAM_APPLY."""
    res = cmd(core, seq, OP["PARAM_SET"], PARAM_ID[name], u16(raw_value))
    assert res["status"] == ACK, f"предусловие: PARAM_SET {name}={raw_value} должен приниматься: {res}"
    return res


def expected_extra_ticks(distance_mm: float, v_mm_s: float, dt: float = TICK_S, cap: float = MAX_STEP) -> int:
    """Число ДОПОЛНИТЕЛЬНЫХ тиков после ACK-тика (который уже делает первый
    шаг — общая модель движения контракта) до прибытия. Тик-инвариант:
    step = min(v*dt, cap); всего тиков = ceil(distance/step); ACK — первый
    из них, значит дополнительных = ceil(distance/step) - 1."""
    step = min(v_mm_s * dt, cap)
    return math.ceil(distance_mm / step) - 1


# Дефолтная рабочая зона (все P_WS_* по умолчанию, см. params_v2.PARAMS) —
# используется и напрямую (как оракул geometry.check_point), и как справка
# для литералов в тестах ниже. Числа сверены с PARAMS: P_WS_R_MIN=1000/10=100,
# P_WS_R_MAX=6000/10=600, P_WS_Z_MIN=-1500/10=-150, P_WS_Z_MAX=0,
# P_WS_RZ_MIN=-3600/10=-360, P_WS_RZ_MAX=3600/10=360,
# P_WS_ANG_MIN=-1650/10=-165, P_WS_ANG_MAX=1650/10=165, P_WS_BOX_EN=0 (выкл).
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


# =========================================================================== #
# Пункт 1: модель движения — интерполяция, тайминг, ACK-тик = первый шаг
# =========================================================================== #


def test_tick_interval_s_constant_matches_contract():
    assert sim_core_v2.TICK_INTERVAL_S == pytest.approx(0.01)


def test_max_step_mm_constant_matches_contract():
    assert sim_core_v2.MAX_STEP_MM == pytest.approx(100.0 / 3.0)


def test_ptp_line_monotonic_over_ge3_ticks_and_arrives_exactly():
    # из дома (300,-210,-40,-100) в (400,-210,-40,-100): дистанция 100мм по X.
    # r=sqrt(400²+210²)=451.8 в [100,600]; angle=atan2(-210,400)=-27.7° в
    # [-165,165]; сегмент горизонтален на y=-210, ближайшая к (0,0) точка —
    # x=300 (мин. |x| на отрезке), расстояние 300+ >> r_min=100 -> без мёртвой
    # зоны. hand: TLM_HAND после boot = P_HAND по умолчанию (см. контракт).
    core = fresh_core()
    servo_on(core, 1)
    hx, hy, hz, hrz = home_target()
    tx, ty, tz, trz = hx + 1000, hy, hz, hrz  # +100.0мм по X (raw ×0.1)
    res = cmd(core, 2, OP["PTP_MOVE"], tx, ty, tz, trz, KIND["LINE"], 100)
    assert res["status"] == ACK
    move_seq = res["seq"]
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == 1  # PTP
    assert core.read(REG["TLM_MOVING"], 1)[0] == 1

    prev_x = core.read(REG["TLM_X"], 1)[0]
    assert hx <= prev_x <= tx  # уже сделан первый шаг ACK-тиком
    ticks = 0
    while core.read(REG["TLM_ACTIVITY"], 1)[0] != 0 and ticks < 500:
        core.tick()
        ticks += 1
        cur_x = core.read(REG["TLM_X"], 1)[0]
        assert prev_x <= cur_x <= tx, "координата X должна монотонно приближаться к цели, не перелетая"
        prev_x = cur_x
    assert ticks >= 3, "движение ≥100мм обязано занять минимум 3 тика (MAX_STEP_MM)"
    assert core.read(REG["TLM_X"], 1)[0] == tx
    assert s16(core.read(REG["TLM_Y"], 1)[0]) == ty
    assert s16(core.read(REG["TLM_Z"], 1)[0]) == tz
    assert s16(core.read(REG["TLM_RZ"], 1)[0]) == trz
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == 0
    assert core.read(REG["TLM_MOVING"], 1)[0] == 0
    assert core.read(REG["TLM_DONE_SEQ"], 1)[0] == move_seq


@pytest.mark.parametrize(
    "spd_pct,pct_used,label",
    [
        (100, 100, "100%"),
        (10, 10, "10%"),
        (0, None, "0->P_SPD_DEFAULT(80%)"),
    ],
)
def test_ptp_line_tick_count_matches_speed_formula(spd_pct, pct_used, label):
    # та же дистанция 100мм по X, что и в предыдущем тесте. v = P_SPD_L(1500
    # мм/с default) * pct/100; spd_pct=0 -> pct=P_SPD_DEFAULT(80% default).
    # step = min(v*0.01, 100/3); доп.тиков после ACK = ceil(100/step) - 1.
    core = fresh_core()
    servo_on(core, 1)
    hx, hy, hz, hrz = home_target()
    tx, ty, tz, trz = hx + 1000, hy, hz, hrz
    res = cmd(core, 2, OP["PTP_MOVE"], tx, ty, tz, trz, KIND["LINE"], spd_pct)
    assert res["status"] == ACK, label

    spd_l = PARAMS[PARAM_ID["P_SPD_L"]]["default"]  # 1500 мм/с, scale=1 (raw==eng)
    pct = pct_used if pct_used is not None else PARAMS[PARAM_ID["P_SPD_DEFAULT"]]["default"]
    v = spd_l * pct / 100.0
    expected = expected_extra_ticks(100.0, v)

    extra = run_until_activity_zero(core, max_ticks=200)
    assert extra == expected, f"{label}: v={v} мм/с, ожидалось {expected} доп.тиков, получено {extra}"


def test_max_step_mm_caps_displacement_on_explicit_large_dt():
    # спустя ACK (dt по умолчанию 0.01, шаг 15мм, не задевает потолок),
    # один явный tick(dt_s=1.0) при v=1500мм/с дал бы 1500мм — обязан быть
    # обрезан до MAX_STEP_MM=100/3≈33.33мм (raw 333, округление до 0.1мм).
    core = fresh_core()
    servo_on(core, 1)
    hx, hy, hz, hrz = home_target()
    tx, ty, tz, trz = hx + 1000, hy, hz, hrz  # 100мм, точно капа хватает и с запасом
    res = cmd(core, 2, OP["PTP_MOVE"], tx, ty, tz, trz, KIND["LINE"], 100)
    assert res["status"] == ACK
    x_after_ack = core.read(REG["TLM_X"], 1)[0]

    core.tick(1.0)
    x_after_big_tick = core.read(REG["TLM_X"], 1)[0]
    delta_mm = (x_after_big_tick - x_after_ack) / 10.0
    assert delta_mm == pytest.approx(100.0 / 3.0, abs=0.1), (
        f"шаг должен быть ровно MAX_STEP_MM≈33.33мм, получено {delta_mm}мм"
    )
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] != 0, "движение не должно завершиться этим одним тиком"


def test_ptp_joint_arrival_sets_hand_and_ticks_default_dt_when_omitted():
    # tick() без аргумента -> dt=TICK_INTERVAL_S(0.01), не мгновенный телепорт.
    core = fresh_core()
    servo_on(core, 1)
    hx, hy, hz, hrz = home_target()
    tx, ty, tz, trz = hx + 1500, hy, hz, hrz  # 150мм
    res = cmd(core, 2, OP["PTP_MOVE"], tx, ty, tz, trz, KIND["JOINT"], 100)
    assert res["status"] == ACK
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] != 0  # не завершилось на ACK-тике
    run_until_activity_zero(core)
    assert core.read(REG["TLM_X"], 1)[0] == tx
    p_hand = PARAMS[PARAM_ID["P_HAND"]]["default"]
    assert core.read(REG["TLM_HAND"], 1)[0] == p_hand


def test_home_arrival_after_moving_away_returns_monotonically():
    core = fresh_core()
    servo_on(core, 1)
    hx, hy, hz, hrz = home_target()
    away_x = hx + 1500  # уйти на 150мм от дома LINE-ходом
    res = cmd(core, 2, OP["PTP_MOVE"], away_x, hy, hz, hrz, KIND["LINE"], 100)
    assert res["status"] == ACK
    run_until_activity_zero(core)
    assert core.read(REG["TLM_X"], 1)[0] == away_x

    home_res = cmd(core, 3, OP["HOME"], 100)
    assert home_res["status"] == ACK
    prev_x = core.read(REG["TLM_X"], 1)[0]
    assert prev_x <= away_x
    ticks = 0
    while core.read(REG["TLM_ACTIVITY"], 1)[0] != 0 and ticks < 500:
        core.tick()
        ticks += 1
        cur_x = core.read(REG["TLM_X"], 1)[0]
        assert cur_x <= prev_x, "HOME должен монотонно приближаться (X убывает назад к дому)"
        prev_x = cur_x
    assert ticks >= 3
    assert core.read(REG["TLM_X"], 1)[0] == hx
    assert s16(core.read(REG["TLM_Y"], 1)[0]) == hy
    assert s16(core.read(REG["TLM_Z"], 1)[0]) == hz
    assert s16(core.read(REG["TLM_RZ"], 1)[0]) == hrz
    assert core.read(REG["TLM_HAND"], 1)[0] == PARAMS[PARAM_ID["P_HAND"]]["default"]  # HOME — JOINT-тип
    assert core.read(REG["TLM_DONE_SEQ"], 1)[0] == home_res["seq"]


def test_jog_step_monotonic_and_arrives_exactly():
    core = fresh_core()
    servo_on(core, 1)
    hx, hy, hz, hrz = home_target()
    dx = 1500  # 150мм по X, < P_JOG_MAX(200мм default) — валидный JOG_STEP
    res = cmd(core, 2, OP["JOG_STEP"], dx, 0, 0, 0, 100)
    assert res["status"] == ACK
    tx = hx + dx
    prev_x = core.read(REG["TLM_X"], 1)[0]
    ticks = 0
    while core.read(REG["TLM_ACTIVITY"], 1)[0] != 0 and ticks < 500:
        core.tick()
        ticks += 1
        cur_x = core.read(REG["TLM_X"], 1)[0]
        assert prev_x <= cur_x <= tx
        prev_x = cur_x
    assert core.read(REG["TLM_X"], 1)[0] == tx
    assert core.read(REG["TLM_DONE_SEQ"], 1)[0] == res["seq"]


def test_current_pose_for_next_move_is_read_from_registers_at_rest():
    # "поза в начале команды читается из регистров позы (в покое — истина)":
    # второй ход стартует из места прибытия первого, а не из boot-позы.
    core = fresh_core()
    servo_on(core, 1)
    hx, hy, hz, hrz = home_target()
    mid_x = hx + 1000
    r1 = cmd(core, 2, OP["PTP_MOVE"], mid_x, hy, hz, hrz, KIND["LINE"], 100)
    assert r1["status"] == ACK
    run_until_activity_zero(core)
    assert core.read(REG["TLM_X"], 1)[0] == mid_x

    final_x = mid_x + 500
    r2 = cmd(core, 3, OP["PTP_MOVE"], final_x, hy, hz, hrz, KIND["LINE"], 100)
    assert r2["status"] == ACK
    x_after_ack = core.read(REG["TLM_X"], 1)[0]
    assert mid_x <= x_after_ack <= final_x, "второй ход должен стартовать из mid_x, не из home"


# =========================================================================== #
# Пункт 2: зона, R_KIND, R_HAND, R_JOG_TOO_LONG, R_DEAD_ZONE
# =========================================================================== #


def test_ptp_joint_target_zone_matches_geometry_oracle():
    """geometry.check_point — уже принятый (T2.0) независимый оракул; контракт
    прямо требует, чтобы симулятор использовал ЕГО, не копию. Точки — те же
    дефолты зоны, что и в DEFAULT_WS выше."""
    cases = [
        (300.0, 0.0, -75.0, 0.0, True),  # r=300 в [100,600], z ok, angle=0
        (50.0, 0.0, -75.0, 0.0, False),  # r=50 < r_min=100
        (650.0, 0.0, -75.0, 0.0, False),  # r=650 > r_max=600
    ]
    for x, y, z, rz, ok in cases:
        oracle = check_point(DEFAULT_WS, x, y, z, rz)
        assert oracle == (0 if ok else REASON["R_OUT_OF_ZONE"])  # самопроверка оракула

        core = fresh_core()
        servo_on(core, 1)
        res = cmd(core, 2, OP["PTP_MOVE"], mm(x), mm(y), mm(z), mm(rz), KIND["JOINT"], 100)
        if ok:
            assert res["status"] == ACK, (x, y, z, rz)
        else:
            assert res["status"] == NAK, (x, y, z, rz)
            assert res["errno"] == ERR["E_RANGE"]
            assert res["rvalc"] == 1
            assert res["rvals"][0] == REASON["R_OUT_OF_ZONE"]


@pytest.mark.parametrize(
    "x_eng,y_eng,label",
    [
        (99.9, 0.0, "reject r<r_min"),
        (100.0, 0.0, "accept r=r_min (граница включительна)"),
    ],
)
def test_zone_r_min_boundary(x_eng, y_eng, label):
    # r = sqrt(x²+y²) = |x| (y=0); r_min=100мм default. z=-75 (в [-150,0]),
    # rz=0 (в [-360,360]) — нейтральны, изолируют проверку r.
    core = fresh_core(model=_NO_JOINT_LIMITS)
    servo_on(core, 1)
    res = cmd(core, 2, OP["PTP_MOVE"], mm(x_eng), mm(y_eng), mm(-75.0), mm(0.0), KIND["JOINT"], 100)
    if x_eng < 100.0:
        assert res["status"] == NAK, label
        assert res["errno"] == ERR["E_RANGE"]
        assert res["rvals"][0] == REASON["R_OUT_OF_ZONE"]
    else:
        assert res["status"] == ACK, label


@pytest.mark.parametrize(
    "x_eng,label",
    [(600.1, "reject r>r_max"), (600.0, "accept r=r_max")],
)
def test_zone_r_max_boundary(x_eng, label):
    core = fresh_core()
    servo_on(core, 1)
    res = cmd(core, 2, OP["PTP_MOVE"], mm(x_eng), mm(0.0), mm(-75.0), mm(0.0), KIND["JOINT"], 100)
    if x_eng > 600.0:
        assert res["status"] == NAK, label
        assert res["errno"] == ERR["E_RANGE"]
        assert res["rvals"][0] == REASON["R_OUT_OF_ZONE"]
    else:
        assert res["status"] == ACK, label


@pytest.mark.parametrize(
    "z_eng,label",
    [(-150.1, "reject z<z_min"), (-150.0, "accept z=z_min")],
)
def test_zone_z_min_boundary(z_eng, label):
    # x=300 -> r=300 в [100,600]; rz=0.
    core = fresh_core()
    servo_on(core, 1)
    res = cmd(core, 2, OP["PTP_MOVE"], mm(300.0), mm(0.0), mm(z_eng), mm(0.0), KIND["JOINT"], 100)
    if z_eng < -150.0:
        assert res["status"] == NAK, label
        assert res["errno"] == ERR["E_RANGE"]
        assert res["rvals"][0] == REASON["R_OUT_OF_ZONE"]
    else:
        assert res["status"] == ACK, label


@pytest.mark.parametrize(
    "z_eng,label",
    [(0.1, "reject z>z_max"), (0.0, "accept z=z_max")],
)
def test_zone_z_max_boundary(z_eng, label):
    core = fresh_core()
    servo_on(core, 1)
    res = cmd(core, 2, OP["PTP_MOVE"], mm(300.0), mm(0.0), mm(z_eng), mm(0.0), KIND["JOINT"], 100)
    if z_eng > 0.0:
        assert res["status"] == NAK, label
        assert res["errno"] == ERR["E_RANGE"]
        assert res["rvals"][0] == REASON["R_OUT_OF_ZONE"]
    else:
        assert res["status"] == ACK, label


@pytest.mark.parametrize(
    "rz_eng,label",
    [(-360.1, "reject rz<rz_min"), (-360.0, "accept rz=rz_min")],
)
def test_zone_rz_min_boundary(rz_eng, label):
    core = fresh_core()
    servo_on(core, 1)
    res = cmd(core, 2, OP["PTP_MOVE"], mm(300.0), mm(0.0), mm(-75.0), mm(rz_eng), KIND["JOINT"], 100)
    if rz_eng < -360.0:
        assert res["status"] == NAK, label
        assert res["errno"] == ERR["E_RANGE"]
        assert res["rvals"][0] == REASON["R_OUT_OF_ZONE"]
    else:
        assert res["status"] == ACK, label


@pytest.mark.parametrize(
    "rz_eng,label",
    [(360.1, "reject rz>rz_max"), (360.0, "accept rz=rz_max")],
)
def test_zone_rz_max_boundary(rz_eng, label):
    core = fresh_core()
    servo_on(core, 1)
    res = cmd(core, 2, OP["PTP_MOVE"], mm(300.0), mm(0.0), mm(-75.0), mm(rz_eng), KIND["JOINT"], 100)
    if rz_eng > 360.0:
        assert res["status"] == NAK, label
        assert res["errno"] == ERR["E_RANGE"]
        assert res["rvals"][0] == REASON["R_OUT_OF_ZONE"]
    else:
        assert res["status"] == ACK, label


def test_zone_angle_sector_min_boundary():
    # r=300, angle=-164.5° (внутри сектора [-165,165]) -> x=300cos(-164.5°)=
    # -289.09мм, y=300sin(-164.5°)=-80.19мм; raw=(-2891,-802) (округление до
    # 0.1мм), реальный угол по округлённым raw = -164.4953° (проверено
    # numpy-независимым расчётом ниже в комментарии, пересчитано python'ом
    # при составлении теста) — безопасно внутри границы.
    # angle=-165.5° (снаружи) -> x=300cos(-165.5°)=-290.44мм,
    # y=300sin(-165.5°)=-75.14мм; raw=(-2904,-751), реальный угол -165.5005°.
    # Отступ 0.5° от границы выбран сознательно (не 0.0°), чтобы округление
    # x/y до 0.1мм не могло случайно перекинуть точку на другую сторону
    # границы — см. отчёт, раздел «интерпретации».
    core = fresh_core()
    servo_on(core, 1)
    res_reject = cmd(core, 2, OP["PTP_MOVE"], -2904, -751, mm(-75.0), mm(0.0), KIND["JOINT"], 100)
    assert res_reject["status"] == NAK
    assert res_reject["errno"] == ERR["E_RANGE"]
    assert res_reject["rvals"][0] == REASON["R_OUT_OF_ZONE"]

    res_accept = cmd(core, 3, OP["PTP_MOVE"], -2891, -802, mm(-75.0), mm(0.0), KIND["JOINT"], 100)
    assert res_accept["status"] == ACK


def test_zone_angle_sector_max_boundary():
    # зеркально предыдущему по Y: angle=+164.5°(accept) raw=(-2891,802);
    # angle=+165.5°(reject) raw=(-2904,751).
    core = fresh_core(model=_NO_JOINT_LIMITS)
    servo_on(core, 1)
    res_reject = cmd(core, 2, OP["PTP_MOVE"], -2904, 751, mm(-75.0), mm(0.0), KIND["JOINT"], 100)
    assert res_reject["status"] == NAK
    assert res_reject["errno"] == ERR["E_RANGE"]
    assert res_reject["rvals"][0] == REASON["R_OUT_OF_ZONE"]

    res_accept = cmd(core, 3, OP["PTP_MOVE"], -2891, 802, mm(-75.0), mm(0.0), KIND["JOINT"], 100)
    assert res_accept["status"] == ACK


def test_zone_box_boundary_when_enabled():
    # box выключен по умолчанию (P_WS_BOX_EN=0). Включаем и сужаем
    # P_WS_X_MAX до raw=2000 (200.0мм, < r_max=600 — значит именно box, а не
    # кольцо, будет связывающим ограничением). x=200.0 (=box_x_max) -> accept;
    # x=200.1 -> reject (кольцо r=200/200.1 обоим ок, только box режет).
    core = fresh_core()
    servo_on(core, 1)
    set_idle_param(core, 2, "P_WS_BOX_EN", 1)
    set_idle_param(core, 3, "P_WS_X_MAX", 2000)

    res_reject = cmd(core, 4, OP["PTP_MOVE"], mm(200.1), mm(0.0), mm(-75.0), mm(0.0), KIND["JOINT"], 100)
    assert res_reject["status"] == NAK
    assert res_reject["errno"] == ERR["E_RANGE"]
    assert res_reject["rvals"][0] == REASON["R_OUT_OF_ZONE"]

    res_accept = cmd(core, 5, OP["PTP_MOVE"], mm(200.0), mm(0.0), mm(-75.0), mm(0.0), KIND["JOINT"], 100)
    assert res_accept["status"] == ACK


@pytest.mark.parametrize("kind_value", [1, 3])
def test_ptp_move_invalid_kind_is_range_with_r_kind(kind_value):
    core = fresh_core()
    servo_on(core, 1)
    hx, hy, hz, hrz = home_target()
    res = cmd(core, 2, OP["PTP_MOVE"], hx + 500, hy, hz, hrz, kind_value, 100)
    assert res["status"] == NAK
    assert res["errno"] == ERR["E_RANGE"]
    assert res["rvalc"] == 1
    assert res["rvals"][0] == REASON["R_KIND"]
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == 0  # ничего не поехало


def test_ptp_move_spd_pct_over_100_is_range_without_reason():
    core = fresh_core()
    servo_on(core, 1)
    hx, hy, hz, hrz = home_target()
    res = cmd(core, 2, OP["PTP_MOVE"], hx + 500, hy, hz, hrz, KIND["LINE"], 101)
    assert res["status"] == NAK
    assert res["errno"] == ERR["E_RANGE"]
    assert res["rvalc"] == 0, "формат-проверка spd_pct не несёт rval0 (в отличие от R_KIND)"


def test_home_spd_pct_over_100_is_range():
    core = fresh_core()
    servo_on(core, 1)
    res = cmd(core, 2, OP["HOME"], 101)
    assert res["status"] == NAK
    assert res["errno"] == ERR["E_RANGE"]


def test_jog_step_spd_pct_over_100_is_range():
    core = fresh_core()
    servo_on(core, 1)
    res = cmd(core, 2, OP["JOG_STEP"], 100, 0, 0, 0, 101)
    assert res["status"] == NAK
    assert res["errno"] == ERR["E_RANGE"]


def test_hand_mismatch_scenario_line_rejects_joint_accepts_and_updates_hand():
    # сценарий из контракта дословно: PARAM_SET P_HAND=0, потом LINE ->
    # R_HAND, JOINT -> ACK и TLM_HAND==0, потом LINE -> ACK.
    core = fresh_core()
    servo_on(core, 1)
    p_hand_default = PARAMS[PARAM_ID["P_HAND"]]["default"]
    assert core.read(REG["TLM_HAND"], 1)[0] == p_hand_default  # boot: TLM_HAND=P_HAND

    set_idle_param(core, 2, "P_HAND", 0)
    assert core.read(REG["TLM_HAND"], 1)[0] == p_hand_default  # PARAM_SET сам HAND-регистр не трогает

    hx, hy, hz, hrz = home_target()
    line_target = (hx + 500, hy, hz, hrz)  # 50мм; r,angle валидны (см. первый motion-тест)
    res_line_reject = cmd(core, 3, OP["PTP_MOVE"], *line_target, KIND["LINE"], 100)
    assert res_line_reject["status"] == NAK
    assert res_line_reject["errno"] == ERR["E_RANGE"]
    assert res_line_reject["rvals"][0] == REASON["R_HAND"]
    assert pose(core) == home_target()  # ничего не поехало

    res_joint = cmd(core, 4, OP["PTP_MOVE"], *line_target, KIND["JOINT"], 100)
    assert res_joint["status"] == ACK
    run_until_activity_zero(core)
    assert pose(core) == line_target
    assert core.read(REG["TLM_HAND"], 1)[0] == 0

    final_target = (line_target[0] + 500, hy, hz, hrz)
    res_line_accept = cmd(core, 5, OP["PTP_MOVE"], *final_target, KIND["LINE"], 100)
    assert res_line_accept["status"] == ACK


@pytest.mark.parametrize(
    "dx_raw,label",
    [(2001, "reject +0.1мм над P_JOG_MAX"), (2000, "accept ровно P_JOG_MAX")],
)
def test_jog_step_too_long_boundary(dx_raw, label):
    # P_JOG_MAX default raw=2000 (=200.0мм, scale=10). Один осевой dx, так что
    # sqrt(dx²)=|dx| — сравнение raw напрямую эквивалентно сравнению в мм
    # (оба масштабированы ×10 одинаково). dx=2001 raw = 200.1мм > 200.0мм.
    jog_max_raw = PARAMS[PARAM_ID["P_JOG_MAX"]]["default"]
    assert jog_max_raw == 2000  # фиксируем предпосылку арифметики теста
    core = fresh_core()
    servo_on(core, 1)
    res = cmd(core, 2, OP["JOG_STEP"], dx_raw, 0, 0, 0, 50)
    if dx_raw > jog_max_raw:
        assert res["status"] == NAK, label
        assert res["errno"] == ERR["E_RANGE"]
        assert res["rvalc"] == 1
        assert res["rvals"][0] == REASON["R_JOG_TOO_LONG"]
    else:
        assert res["status"] == ACK, label


def test_dead_zone_segment_line_rejected():
    # A на angle=-85°,r=150 (raw x=131,y=-1494); B на angle=+85°,r=150
    # (raw x=131,y=1494). Оба индивидуально валидны (r=150 в [100,600],
    # angle ±85 в [-165,165]). Отрезок A->B — почти вертикаль x≈13.07мм;
    # ближайшая к (0,0) точка отрезка на t=0.5: (13.07,0), расстояние
    # 13.07мм < r_min=100мм -> R_DEAD_ZONE (посчитано geometry-формулой
    # проекции на отрезок, воспроизведено вручную при составлении теста).
    core = fresh_core(model=_NO_JOINT_LIMITS)
    servo_on(core, 1)
    move_to_via_joint(core, 2, 131, -1494, mm(-75.0), mm(0.0))
    assert core.read(REG["TLM_HAND"], 1)[0] == PARAMS[PARAM_ID["P_HAND"]]["default"]

    res = cmd(core, 3, OP["PTP_MOVE"], 131, 1494, mm(-75.0), mm(0.0), KIND["LINE"], 50)
    assert res["status"] == NAK
    assert res["errno"] == ERR["E_RANGE"]
    assert res["rvals"][0] == REASON["R_DEAD_ZONE"]


def test_dead_zone_segment_joint_accepted_same_endpoints():
    core = fresh_core(model=_NO_JOINT_LIMITS)
    servo_on(core, 1)
    move_to_via_joint(core, 2, 131, -1494, mm(-75.0), mm(0.0))

    res = cmd(core, 3, OP["PTP_MOVE"], 131, 1494, mm(-75.0), mm(0.0), KIND["JOINT"], 50)
    assert res["status"] == ACK, "JOINT обходит проверку отрезка -> те же точки принимаются"


# =========================================================================== #
# Порядок проверок: E_NO_SERVO раньше проверки зоны (доказательство порядка)
# =========================================================================== #


def test_no_servo_checked_before_target_zone():
    core = fresh_core()
    cmd(core, 1, OP["SERVO"], 0)  # серво выключено
    # цель заведомо вне зоны (r=50 < r_min=100) — если бы зона проверялась
    # раньше servo, ошибка была бы E_RANGE/R_OUT_OF_ZONE, а не E_NO_SERVO
    res = cmd(core, 2, OP["PTP_MOVE"], mm(50.0), mm(0.0), mm(-75.0), mm(0.0), KIND["JOINT"], 100)
    assert res["status"] == NAK
    assert res["errno"] == ERR["E_NO_SERVO"]


# =========================================================================== #
# Пункт 6: E_NO_SERVO по каждому опкоду движения + восстановление
# =========================================================================== #


@pytest.mark.parametrize(
    "opcode_name,args",
    [
        ("PTP_MOVE", (3000, 0, -750, 0, KIND["LINE"], 100)),
        ("HOME", (100,)),
        ("JOG_STEP", (100, 0, 0, 0, 50)),
        ("JOG_CONT", (1, 10)),
    ],
)
def test_no_servo_for_every_motion_opcode(opcode_name, args):
    core = fresh_core()
    cmd(core, 1, OP["SERVO"], 0)
    res = cmd(core, 2, OP[opcode_name], *args)
    assert res["status"] == NAK, opcode_name
    assert res["errno"] == ERR["E_NO_SERVO"], opcode_name


def test_no_servo_after_halt_then_recovers_with_servo_on():
    core = fresh_core()
    core.write(REG["STOP_REQ"], [STOP_LEVEL["HALT"]])
    core.tick()
    assert core.read(REG["TLM_SERVO"], 1)[0] == 0

    res_denied = cmd(core, 1, OP["PTP_MOVE"], 3000, 0, -750, 0, KIND["JOINT"], 100)
    assert res_denied["status"] == NAK
    assert res_denied["errno"] == ERR["E_NO_SERVO"]

    res_servo = cmd(core, 2, OP["SERVO"], 1)
    assert res_servo["status"] == ACK
    res_move = cmd(core, 3, OP["PTP_MOVE"], 3000, 0, -750, 0, KIND["JOINT"], 100)
    assert res_move["status"] == ACK


# =========================================================================== #
# Пункт 5 (частично) + JOG_CONT: направления, лиза, край зоны, аргументы
# =========================================================================== #


@pytest.mark.parametrize(
    "direction,speed,label",
    [
        (0, 10, "dir=0 вне 1..8"),
        (9, 10, "dir=9 вне 1..8"),
        (1, 0, "speed=0"),
        (1, 51, "speed=51 > P_JOG_CONT_MAX(50)"),
    ],
)
def test_jog_cont_argument_format_nak(direction, speed, label):
    jog_cont_max = PARAMS[PARAM_ID["P_JOG_CONT_MAX"]]["default"]
    assert jog_cont_max == 50  # фиксируем предпосылку
    core = fresh_core()
    servo_on(core, 1)
    res = cmd(core, 2, OP["JOG_CONT"], direction, speed)
    assert res["status"] == NAK, label
    assert res["errno"] == ERR["E_RANGE"], label


def test_jog_cont_speed_equal_to_max_is_accepted():
    core = fresh_core()
    servo_on(core, 1)
    res = cmd(core, 2, OP["JOG_CONT"], 1, 50)  # ровно P_JOG_CONT_MAX
    assert res["status"] == ACK


def test_jog_cont_moves_pose_along_axis_each_tick():
    core = fresh_core()
    servo_on(core, 1)
    move_to_via_joint(core, 2, mm(300.0), mm(0.0), mm(-75.0), mm(0.0))
    res = cmd(core, 3, OP["JOG_CONT"], 1, 10)  # X+, 10мм/с
    assert res["status"] == ACK
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == 2  # JOG
    assert core.read(REG["TLM_MOVING"], 1)[0] == 1
    x0 = core.read(REG["TLM_X"], 1)[0]
    core.write(REG["JOG_LEASE"], [1])
    core.tick(TICK_S)
    x1 = core.read(REG["TLM_X"], 1)[0]
    assert x1 > x0, "JOG_CONT X+ должен увеличивать X с каждым тиком"


def test_jog_cont_ends_done_after_lease_timeout_without_refresh():
    # P_JOG_LEASE_MS default=300мс, TICK_INTERVAL_S=10мс/тик. ACK-тик = отсчёт
    # поводка "уже освежён" (t=0мс). Порог "строго больше" 300мс -> граница
    # где-то между доп.тиком 29 (290мс, ещё не более) и доп.тиком 31
    # (310мс, уже более). Берём окно [28,33] доп.тиков (280..330мс) с
    # запасом ±1 тик на обе стороны интерпретации "считает ли ACK-тик первым
    # доп.тиком" — см. отчёт, раздел «интерпретации».
    core = fresh_core()
    servo_on(core, 1)
    move_to_via_joint(core, 2, mm(300.0), mm(0.0), mm(-75.0), mm(0.0))  # центр зоны, край не будет мешать
    res = cmd(core, 3, OP["JOG_CONT"], 3, 10)  # Y+, 10мм/с, дальше от края
    assert res["status"] == ACK
    move_seq = res["seq"]

    done_at = None
    for i in range(1, 41):
        core.tick(TICK_S)
        if core.read(REG["TLM_ACTIVITY"], 1)[0] == 0:
            done_at = i
            break
        if i <= 27:
            assert core.read(REG["TLM_ACTIVITY"], 1)[0] != 0, f"не должен завершиться раньше поводка (тик {i})"

    assert done_at is not None, "JOG_CONT должен завершиться сам собой после лиза"
    assert 28 <= done_at <= 33, f"ожидалось завершение около 30 доп.тиков (300мс), получено {done_at}"
    assert core.read(REG["TLM_DONE_SEQ"], 1)[0] == move_seq
    assert core.read(REG["TLM_ERRNO_LAST"], 1)[0] == 0  # завершение лиза — не ошибка


def test_jog_cont_continues_while_lease_refreshed_every_tick():
    core = fresh_core()
    servo_on(core, 1)
    move_to_via_joint(core, 2, mm(300.0), mm(0.0), mm(-75.0), mm(0.0))
    res = cmd(core, 3, OP["JOG_CONT"], 3, 10)
    assert res["status"] == ACK

    for i in range(50):  # 500мс, > 300мс лиза, но освежаем каждый тик
        core.write(REG["JOG_LEASE"], [i + 1])
        core.tick(TICK_S)
        assert core.read(REG["TLM_ACTIVITY"], 1)[0] != 0, f"с освежаемым поводком не должен завершаться (тик {i})"


def test_jog_cont_ends_at_zone_edge_staying_inside():
    # старт x=590мм (r=590, в кольце), X+ на 50мм/с, dt=0.01 -> шаг 0.5мм/тик.
    # 600.0мм включительно допустима (ровно r_max) — последний валидный шаг;
    # 600.5мм уже нет -> шаг не делается, jog завершается DONE, поза
    # остаётся <=600.0мм на каждом тике.
    core = fresh_core()
    servo_on(core, 1)
    move_to_via_joint(core, 2, mm(590.0), mm(0.0), mm(-75.0), mm(0.0))
    res = cmd(core, 3, OP["JOG_CONT"], 1, 50)
    assert res["status"] == ACK
    move_seq = res["seq"]

    max_x_seen = core.read(REG["TLM_X"], 1)[0]
    for _ in range(40):
        if core.read(REG["TLM_ACTIVITY"], 1)[0] == 0:
            break
        core.tick(TICK_S)
        x = core.read(REG["TLM_X"], 1)[0]
        assert x <= 6000, "поза не должна выходить за r_max=600мм ни на одном тике"
        max_x_seen = max(max_x_seen, x)
    else:
        pytest.fail("JOG_CONT не завершился за 40 тиков на краю зоны")

    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == 0
    assert core.read(REG["TLM_DONE_SEQ"], 1)[0] == move_seq  # завершение краем зоны — не ошибка
    assert max_x_seen == 6000, f"ожидалось дойти ровно до r_max=600.0мм (raw 6000), получено {max_x_seen}"


@pytest.mark.parametrize(
    "level,expect_servo_off,expect_vfd_delta",
    [
        (STOP_LEVEL["SOFT"], False, 0),
        (STOP_LEVEL["HARD"], False, 0),
        (STOP_LEVEL["HALT"], True, 1),
    ],
)
def test_jog_cont_stop_aborts_immediately_for_every_level(level, expect_servo_off, expect_vfd_delta):
    # в отличие от PTP/HOME/JOG_STEP, для JOG_CONT SOFT тоже "abort now"
    # (контракт: таблица уровней стопа, строка JOG_CONT).
    core = fresh_core()
    servo_on(core, 1)
    move_to_via_joint(core, 2, mm(300.0), mm(0.0), mm(-75.0), mm(0.0))
    res = cmd(core, 3, OP["JOG_CONT"], 3, 10)
    assert res["status"] == ACK
    move_seq = res["seq"]
    # Правка ведущего (T2.2): подготовка (seq 2) уже честно записала DONE_SEQ = 2;
    # обрыв не должен его менять — ждать 0 было ошибкой теста.
    done_before = core.read(REG["TLM_DONE_SEQ"], 1)[0]
    core.tick(TICK_S)
    core.tick(TICK_S)
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] != 0  # всё ещё едет

    vfd_before = core.vfd_stop_requests
    core.write(REG["STOP_REQ"], [level])
    core.tick(TICK_S)

    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == 0, "JOG_CONT обязан прерваться немедленно на любом уровне стопа"
    assert core.read(REG["TLM_MOVING"], 1)[0] == 0
    assert core.read(REG["TLM_ERRNO_LAST"], 1)[0] == ERR["E_ABORTED"]
    assert core.read(REG["TLM_ERR_SEQ"], 1)[0] == move_seq
    assert core.read(REG["TLM_DONE_SEQ"], 1)[0] == done_before
    assert core.read(REG["TLM_STOP_ACK"], 1)[0] == level
    assert core.read(REG["TLM_SERVO"], 1)[0] == (0 if expect_servo_off else 1)
    assert core.vfd_stop_requests == vfd_before + expect_vfd_delta


# =========================================================================== #
# Пункт 7: плоскость стопа — SOFT pending / HARD / HALT на PTP, идемпотентность
# =========================================================================== #


def test_vfd_stop_requests_starts_at_zero():
    core = fresh_core()
    assert core.vfd_stop_requests == 0


@pytest.mark.parametrize("level", [STOP_LEVEL["SOFT"], STOP_LEVEL["HARD"]])
def test_stop_soft_and_hard_idle_are_echo_only_no_side_effects(level):
    core = fresh_core()
    servo_before = core.read(REG["TLM_SERVO"], 1)[0]
    vfd_before = core.vfd_stop_requests
    core.write(REG["STOP_REQ"], [level])
    core.tick()
    assert core.read(REG["TLM_STOP_ACK"], 1)[0] == level
    assert core.read(REG["TLM_SERVO"], 1)[0] == servo_before
    assert core.vfd_stop_requests == vfd_before


def test_stop_halt_idle_kills_servo_and_increments_vfd():
    core = fresh_core()
    assert core.vfd_stop_requests == 0
    core.write(REG["STOP_REQ"], [STOP_LEVEL["HALT"]])
    core.tick()
    assert core.read(REG["TLM_STOP_ACK"], 1)[0] == STOP_LEVEL["HALT"]
    assert core.read(REG["TLM_SERVO"], 1)[0] == 0
    assert core.vfd_stop_requests == 1


def _start_long_ptp(core, seq: int, distance_mm: float = 150.0, spd: int = 20):
    """Долгий LINE-ход (низкая скорость -> много тиков в полёте), для
    stop-plane тестов. Возвращает (seq хода, целевую позу, стартовую позу)."""
    hx, hy, hz, hrz = home_target()
    tx = hx + mm(distance_mm)
    res = cmd(core, seq, OP["PTP_MOVE"], tx, hy, hz, hrz, KIND["LINE"], spd)
    assert res["status"] == ACK
    return res["seq"], (tx, hy, hz, hrz), (hx, hy, hz, hrz)


def test_stop_soft_during_ptp_is_pending_until_arrival_then_aborted():
    core = fresh_core()
    servo_on(core, 1)
    move_seq, target, start = _start_long_ptp(core, 2)
    core.tick()
    core.tick()
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] != 0

    core.write(REG["STOP_REQ"], [STOP_LEVEL["SOFT"]])
    core.tick()
    # pending: движение продолжается, STOP_ACK ЕЩЁ не записан
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] != 0, "SOFT посреди PTP не должен прерывать сразу"
    assert core.read(REG["TLM_STOP_ACK"], 1)[0] == 0

    run_until_activity_zero(core)
    assert core.read(REG["TLM_X"], 1)[0] == target[0]  # доехал до цели
    assert core.read(REG["TLM_DONE_SEQ"], 1)[0] == 0  # НЕ завершение, а обрыв
    assert core.read(REG["TLM_ERRNO_LAST"], 1)[0] == ERR["E_ABORTED"]
    assert core.read(REG["TLM_ERR_SEQ"], 1)[0] == move_seq
    assert core.read(REG["TLM_STOP_ACK"], 1)[0] == STOP_LEVEL["SOFT"]


def test_stop_hard_during_ptp_freezes_pose_strictly_between():
    core = fresh_core()
    servo_on(core, 1)
    move_seq, target, start = _start_long_ptp(core, 2)
    core.tick()
    core.tick()
    vfd_before = core.vfd_stop_requests

    core.write(REG["STOP_REQ"], [STOP_LEVEL["HARD"]])
    core.tick()

    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == 0, "HARD обязан прервать немедленно"
    assert core.read(REG["TLM_MOVING"], 1)[0] == 0
    frozen_x = core.read(REG["TLM_X"], 1)[0]
    assert start[0] < frozen_x < target[0], "поза должна замереть строго между стартом и целью"
    assert core.read(REG["TLM_ERRNO_LAST"], 1)[0] == ERR["E_ABORTED"]
    assert core.read(REG["TLM_ERR_SEQ"], 1)[0] == move_seq
    assert core.read(REG["TLM_DONE_SEQ"], 1)[0] == 0
    assert core.read(REG["TLM_STOP_ACK"], 1)[0] == STOP_LEVEL["HARD"]
    assert core.vfd_stop_requests == vfd_before, "HARD не должен трогать vfd_stop_requests"


def test_stop_halt_during_ptp_aborts_now_kills_servo_and_increments_vfd():
    core = fresh_core()
    servo_on(core, 1)
    move_seq, target, start = _start_long_ptp(core, 2)
    core.tick()
    core.tick()
    vfd_before = core.vfd_stop_requests

    core.write(REG["STOP_REQ"], [STOP_LEVEL["HALT"]])
    core.tick()

    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == 0
    assert core.read(REG["TLM_SERVO"], 1)[0] == 0
    assert core.vfd_stop_requests == vfd_before + 1
    assert core.read(REG["TLM_ERRNO_LAST"], 1)[0] == ERR["E_ABORTED"]
    assert core.read(REG["TLM_STOP_ACK"], 1)[0] == STOP_LEVEL["HALT"]


def test_hard_arriving_while_soft_pending_aborts_now_with_single_event():
    core = fresh_core()
    servo_on(core, 1)
    move_seq, target, start = _start_long_ptp(core, 2)
    core.tick()
    core.write(REG["STOP_REQ"], [STOP_LEVEL["SOFT"]])
    core.tick()
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] != 0  # SOFT ещё pending
    err_evt_before = core.read(REG["TLM_ERR_EVT"], 1)[0]

    core.write(REG["STOP_REQ"], [STOP_LEVEL["HARD"]])
    core.tick()

    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == 0, "HARD должен сработать немедленно, не дожидаясь прибытия"
    frozen_x = core.read(REG["TLM_X"], 1)[0]
    assert start[0] < frozen_x < target[0]
    assert core.read(REG["TLM_ERR_EVT"], 1)[0] == err_evt_before + 1, "ровно ОДНО событие обрыва, не два"
    assert core.read(REG["TLM_STOP_ACK"], 1)[0] == STOP_LEVEL["HARD"], "эхо HARD, не зависшего SOFT"


def test_second_soft_replaces_pending_value_echoed_on_arrival():
    core = fresh_core()
    servo_on(core, 1)
    move_seq, target, start = _start_long_ptp(core, 2)
    core.tick()
    core.write(REG["STOP_REQ"], [STOP_LEVEL["SOFT"]])  # значение 1
    core.tick()
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] != 0
    err_evt_before = core.read(REG["TLM_ERR_EVT"], 1)[0]

    core.write(REG["STOP_REQ"], [5])  # тоже SOFT (5%4=1), другое значение
    core.tick()
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] != 0, "второй SOFT тоже pending, не abort now"

    run_until_activity_zero(core)
    assert core.read(REG["TLM_X"], 1)[0] == target[0]
    assert core.read(REG["TLM_STOP_ACK"], 1)[0] == 5, "эхо должно быть последним pending-значением"
    assert core.read(REG["TLM_ERR_EVT"], 1)[0] == err_evt_before + 1, "ровно одно событие обрыва на весь сценарий"


def test_err_evt_written_after_servo_off_on_halt_abort_during_real_motion():
    # тот же порядок И5, что и в T2.1, но теперь на настоящем движении (не
    # заглушке): SERVO=0 должен попасть в блок события раньше ERR_EVT.
    core = recording_core()
    servo_on(core, 1)
    _start_long_ptp(core, 2)
    core.tick()
    core.write(REG["STOP_REQ"], [STOP_LEVEL["HALT"]])
    core.regs.write_log.clear()
    core.tick()
    log = core.regs.write_log
    assert last_pos(log, REG["TLM_SERVO"]) < first_pos(log, REG["TLM_ERR_EVT"])


def test_stop_ack_written_after_err_evt_on_hard_abort():
    core = recording_core()
    servo_on(core, 1)
    _start_long_ptp(core, 2)
    core.tick()
    core.write(REG["STOP_REQ"], [STOP_LEVEL["HARD"]])
    core.regs.write_log.clear()
    core.tick()
    log = core.regs.write_log
    assert first_pos(log, REG["TLM_STOP_ACK"]) > last_pos(log, REG["TLM_ERR_EVT"])


def test_done_seq_written_after_pose_activity_moving_on_real_arrival():
    # T2.1 проверял это на заглушке-телепорте; здесь — на настоящем
    # интерполируемом движении (несколько тиков, не один).
    core = recording_core()
    servo_on(core, 1)
    move_seq, target, start = _start_long_ptp(core, 2, distance_mm=150.0, spd=100)
    log = None
    for _ in range(200):
        core.regs.write_log.clear()
        core.tick()
        if core.read(REG["TLM_ACTIVITY"], 1)[0] == 0:
            log = list(core.regs.write_log)
            break
    else:
        pytest.fail("команда не завершилась за 200 тиков")
    done_pos = first_pos(log, REG["TLM_DONE_SEQ"])
    assert last_pos(log, REG["TLM_ACTIVITY"]) < done_pos
    assert last_pos(log, REG["TLM_MOVING"]) < done_pos
    assert last_pos(log, REG["TLM_X"]) < done_pos  # поза тоже должна лечь до DONE_SEQ


# =========================================================================== #
# Пункт 8 (FAULT): inject_motion_fault, gating, CLEAR_ERR -> IDLE
# =========================================================================== #


def test_inject_motion_fault_while_idle():
    core = fresh_core()
    err_evt_before = core.read(REG["TLM_ERR_EVT"], 1)[0]
    core.inject_motion_fault()
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == 5  # FAULT
    assert core.read(REG["TLM_MOVING"], 1)[0] == 0
    assert core.read(REG["TLM_ERRNO_LAST"], 1)[0] == ERR["E_MOTION_FAULT"]
    assert core.read(REG["TLM_ERR_SEQ"], 1)[0] == 0  # команды не было
    assert core.read(REG["TLM_ERR_EVT"], 1)[0] == err_evt_before + 1


def test_inject_motion_fault_while_moving_freezes_pose_and_ends_command():
    core = fresh_core()
    servo_on(core, 1)
    move_seq, target, start = _start_long_ptp(core, 2)
    core.tick()
    core.tick()
    frozen_before = pose(core)

    core.inject_motion_fault()

    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == 5
    assert core.read(REG["TLM_MOVING"], 1)[0] == 0
    assert core.read(REG["TLM_ERR_SEQ"], 1)[0] == move_seq
    assert core.read(REG["TLM_ERRNO_LAST"], 1)[0] == ERR["E_MOTION_FAULT"]
    assert pose(core) == frozen_before

    core.tick()  # проба: в FAULT движение не должно продолжаться
    assert pose(core) == frozen_before


@pytest.mark.parametrize(
    "opcode_name,args",
    [
        ("PING", ()),
        ("PARAM_GET", (PARAM_ID["P_SPD_DEFAULT"],)),
        ("PARAM_SET", (PARAM_ID["P_SPD_DEFAULT"], 50)),
        ("SERVO", (1,)),
    ],
)
def test_fault_gating_allows_whitelist(opcode_name, args):
    core = fresh_core()
    servo_on(core, 1)
    core.inject_motion_fault()
    res = cmd(core, 2, OP[opcode_name], *args)
    assert res["status"] == ACK, f"{opcode_name} должен приниматься в FAULT: {res}"


@pytest.mark.parametrize(
    "opcode_name,args",
    [
        ("DO_SET", (1, 1)),
        ("PTP_MOVE", (3000, 0, -750, 0, KIND["JOINT"], 100)),
        ("HOME", (100,)),
        ("JOG_STEP", (100, 0, 0, 0, 50)),
        ("JOG_CONT", (1, 10)),
        ("PARAM_APPLY", ()),
    ],
)
def test_fault_gating_rejects_everything_else_with_busy(opcode_name, args):
    core = fresh_core()
    servo_on(core, 1)
    core.inject_motion_fault()
    res = cmd(core, 2, OP[opcode_name], *args)
    assert res["status"] == NAK, opcode_name
    assert res["errno"] == ERR["E_BUSY"], opcode_name


def test_clear_err_in_fault_returns_to_idle():
    core = fresh_core()
    servo_on(core, 1)
    core.inject_motion_fault()
    err_evt_before = core.read(REG["TLM_ERR_EVT"], 1)[0]

    res = cmd(core, 2, OP["CLEAR_ERR"])
    assert res["status"] == ACK
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == 0
    assert core.read(REG["TLM_ERRNO_LAST"], 1)[0] == 0
    assert core.read(REG["TLM_ERR_SEQ"], 1)[0] == 0
    assert core.read(REG["TLM_ERR_EVT"], 1)[0] == err_evt_before  # событие не откатывается
