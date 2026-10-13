"""Слепая приёмка T3.9: стартовое состояние сценария в ``SC_RUN`` и его перенос через границу куска.

Purpose:
    Доказать контракт T3.9 (protocol-spec §5, §6, §7.2, §7.4 после правки):
    ``SC_RUN(count, sc_id, offset, spd_pct, accel, accur)`` применяет стартовое состояние до первого
    движения куска (0 -- «не задано», то есть текущий параметр; ``accur`` на проводе сдвинут на +1);
    значение вне диапазона -- NAK ``E_RANGE [R_APARAM]`` без движения и без следов; на выходе из сценария
    действуют умолчания; ``run_chunks`` передаёт в кусок k+1 состояние конца куска k; след ``[v2] SC rec``
    несёт поля ``acc=`` и ``accur=``. Ядро проверяется без TCP (тики по 0.01 с), перенос через границу куска
    и клиентский NAK -- по проводу Modbus/TCP на обвязке T3.5.

Что весь файл НЕ доказывает:
    - влияние ACCEL и ACCUR на движение: sim их только хранит, наблюдаемы лишь поля следа ``acc=``/``accur=``;
    - прошивку: обработчик ``SC_RUN`` на контроллере -- Ф4;
    - сглаживание ``LINE_PASS`` и поведение настоящего контроллера.

Окна и таймауты меряются во времени sim (число тиков по 0.01 с, штампы ``Tick.t``), не по стенным часам;
стенное время -- только верхний дедлайн блокирующих вызовов (``bounded``, ``timeout_s`` обвязки). Ожидаемые
значения -- литералы брифа ``plans/robot-protocol-v2/tasks/T3.9.tester.md``, не выведенные из кода под проверкой.
"""

from __future__ import annotations

import re

import pytest

from Services.robot_comm import ROBOT_AVAILABLE
from Services.robot_comm.core.params_v2 import PARAM_ID
from Services.robot_comm.core.protocol_v2 import CONSTANTS, OP, REG
from Services.robot_comm.core.wire_v2 import encode_scenario
from Services.robot_comm.errors import RobotNak
from Services.robot_comm.programs import Action, FrameDef, Move, Point, Program, compile_program
from Services.robot_comm.programs.generators import draw, return_slot
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2
from Services.robot_comm.tests.e2e_rig_v2 import WS_PARAMS, E2eRig, bounded

__all__: list[str] = []

pytestmark = pytest.mark.skipif(not ROBOT_AVAILABLE, reason="Services.robot_comm недоступен")

# ---------------------------------------------------------------------------
# Фикстуры брифа (литералы)
# ---------------------------------------------------------------------------

ACK = 1
NAK = 2
E_BAD_ARGC = 2
E_RANGE = 3
R_APARAM = 3
ACTIVITY_IDLE = 0
ACTIVITY_SCENARIO = 4

SLOT = Point(name="slot", x=350, y=-150, z=-90, rz=10, hand=1)
SLOT_KINDS = ["JOINT", "LINE", "LINE", "LINE", "LINE", "LINE", "LINE"]
SLOT_ACTS = [(1, 2, "DO_ON", 1.0), (1, 3, "DELAY_MS", 400.0), (1, 6, "DO_OFF", 1.0), (1, 7, "DELAY_MS", 400.0)]
HOME_POSE = (300.0, -210.0, -40.0, -100.0)

SHEET = FrameDef(
    name="sheet",
    origin=(300, -100, -100),
    on_x=(400, -100, -100),
    in_plane=(300, 0, -100),
)
FRAMES = {"sheet": SHEET}
STROKE100 = (tuple((0.5 * j, 20) for j in range(100)),)

_REC_RX = re.compile(r"SC rec id=(\d+) i=(\d+) kind=(\w+) spd=(\d+) acc=(\d+) accur=(\d+)")
_ACT_RX = re.compile(r"SC act id=(\d+) i=(\d+) act=(\w+) val=(-?\d+(?:\.\d+)?)")
_END_RX = re.compile(r"SC end id=(\d+) done_n=(\d+)")

type Rec = tuple[int, int, str, int, int, int]  # (id, i, kind, spd, acc, accur)
type Act = tuple[int, int, str, float]  # (id, i, act, val)


# ---------------------------------------------------------------------------
# Разбор следа
# ---------------------------------------------------------------------------


def _recs(texts: list[str]) -> list[Rec]:
    """Строки ``SC rec`` в порядке следа; строка, не прошедшая регулярку, -- провал с текстом строки."""
    out: list[Rec] = []
    for text in texts:
        if "SC rec" not in text:
            continue
        m = _REC_RX.search(text)
        if m is None:
            pytest.fail(f"строка SC rec не разбирается регуляркой (нет acc=/accur=?): {text!r}")
        out.append((int(m[1]), int(m[2]), m[3], int(m[4]), int(m[5]), int(m[6])))
    return out


def _acts(texts: list[str]) -> list[Act]:
    out: list[Act] = []
    for text in texts:
        m = _ACT_RX.search(text)
        if m is not None:
            out.append((int(m[1]), int(m[2]), m[3], float(m[4])))
    return out


def _ends(texts: list[str]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for text in texts:
        m = _END_RX.search(text)
        if m is not None:
            out.append((int(m[1]), int(m[2])))
    return out


def _event_texts(rig: E2eRig, after: int = 0) -> list[str]:
    return [text for _t, text in rig.core.events()[after:]]


# ---------------------------------------------------------------------------
# Хелперы ядра без TCP
# ---------------------------------------------------------------------------


def _send(core: RobotSimCoreV2, seq: int, opcode: int, *args: int) -> None:
    """Команда в mailbox и ровно один тик (разбор mailbox -- на тике). Каждый вызов -- новый ``seq``."""
    core.write(REG["CMD_SEQ"], [seq])
    core.write(REG["CMD_OPCODE"], [opcode])
    core.write(REG["CMD_ARGC"], [len(args)])
    if args:
        core.write(REG["CMD_ARGS"], [a & 0xFFFF for a in args])
    core.write(REG["CMD_FLAG"], [1])
    core.tick(0.01)


def _res(core: RobotSimCoreV2) -> tuple[int, int, int, int]:
    """``(RES_STATUS, RES_ERRNO, RES_RVALC, RES_RVALS[0])``."""
    return (
        core.read(REG["RES_STATUS"], 1)[0],
        core.read(REG["RES_ERRNO"], 1)[0],
        core.read(REG["RES_RVALC"], 1)[0],
        core.read(REG["RES_RVALS"], 1)[0],
    )


def _reg(core: RobotSimCoreV2, name: str) -> int:
    return core.read(REG[name], 1)[0]


class _Stand:
    """Ядро sim с трассировкой сценария и счётчиком ``seq`` (каждая команда -- новый ``seq``)."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.core = RobotSimCoreV2(trace_sc=True, on_event=self.lines.append)
        self._seq = 0

    def send(self, opcode: int, *args: int) -> tuple[int, int, int, int]:
        self._seq += 1
        _send(self.core, self._seq, opcode, *args)
        return _res(self.core)

    def servo_on(self) -> None:
        self.set_servo(1)

    def set_servo(self, on: int) -> None:
        # sim стартует с включённым серво (T3.9, матрица I5): «выключено» надо выключить явно и проверить
        status = self.send(OP["SERVO"], on)[0]
        assert status == ACK
        for _ in range(50):
            if _reg(self.core, "TLM_SERVO") == on:
                break
            self.core.tick(0.01)
        assert _reg(self.core, "TLM_SERVO") == on

    def param_set(self, name: str, value: int) -> None:
        assert self.send(OP["PARAM_SET"], PARAM_ID[name], value)[0] == ACK, f"PARAM_SET {name}={value} не принят"

    def load_slot(self) -> None:
        """7 записей ``return_slot(SLOT)`` в ``SC_BUF`` с offset 0."""
        gp = return_slot(SLOT)
        scenario = compile_program(gp.program, gp.points, {}, WS_PARAMS)
        words = encode_scenario(scenario, params=WS_PARAMS, round_step=0.1)
        assert len(words) == 7
        for index, record in enumerate(words):
            self.core.write(REG["SC_BUF"] + index * CONSTANTS["SC_STRIDE"], list(record))

    def run_to_end(self, *, expect_spd: int | None = None) -> int:
        """Тики по 0.01 до ``TLM_ACTIVITY == 0`` (не больше 3000).

        Если задан ``expect_spd``: на каждом наблюдении с ``TLM_ACTIVITY == 4`` (первое -- сразу после ``_send``)
        ``TLM_SPD_PCT`` равен ему. Возвращает число проверенных наблюдений.
        """
        checked = 0
        for _ in range(3000):
            activity = _reg(self.core, "TLM_ACTIVITY")
            if activity == ACTIVITY_IDLE:
                return checked
            if expect_spd is not None and activity == ACTIVITY_SCENARIO:
                assert _reg(self.core, "TLM_SPD_PCT") == expect_spd, f"TLM_SPD_PCT на наблюдении {checked + 1}"
                checked += 1
            self.core.tick(0.01)
        pytest.fail("сценарий не завершился за 3000 тиков")


def _slot_recs(sc_id: int, spd: int, acc: int, accur: int) -> list[Rec]:
    return [(sc_id, n, SLOT_KINDS[n - 1], spd, acc, accur) for n in range(1, 8)]


# ---------------------------------------------------------------------------
# a-d. Ядро без TCP
# ---------------------------------------------------------------------------


def test_sc_run_zeros_use_current_defaults():
    """Нули в ``SC_RUN`` -- текущие значения параметров, а не литералы YAML.

    ``P_SPD_DEFAULT`` 55, ``P_ACC_L`` 20000, ``P_ACCUR_DEFAULT`` 1: все 7 строк ``SC rec`` несут их, после
    конца ``TLM_SPD_PCT`` == 55. НЕ доказывает: влияние ACCEL/ACCUR на движение, прошивку.
    """
    stand = _Stand()
    stand.servo_on()
    stand.param_set("P_SPD_DEFAULT", 55)
    stand.param_set("P_ACC_L", 20000)
    stand.param_set("P_ACCUR_DEFAULT", 1)
    stand.load_slot()

    assert stand.send(OP["SC_RUN"], 7, 1, 0, 0, 0, 0)[0] == ACK
    stand.run_to_end()

    assert _recs(stand.lines) == _slot_recs(1, 55, 20000, 1)
    assert _acts(stand.lines) == SLOT_ACTS
    assert _reg(stand.core, "TLM_SPD_PCT") == 55


def test_sc_run_start_state_applies_from_first_record():
    """Стартовое состояние действует с первой записи, а на выходе из сценария -- умолчания.

    ``SC_RUN(7, 1, 0, 30, 30000, 2)``: на каждом тике сценария ``TLM_SPD_PCT`` == 30, все 7 строк ``SC rec``
    id=1 -- ``spd=30 acc=30000 accur=1``; после конца ``TLM_SPD_PCT`` == 80. Следующий ``SC_RUN`` с нулями
    на том же ядре -- снова ``spd=80 acc=25000 accur=0`` (состояние прошлого прогона не утекло, §7.2 п.5).
    НЕ доказывает: влияние ACCEL/ACCUR на движение, прошивку.
    """
    stand = _Stand()
    stand.servo_on()
    stand.load_slot()

    assert stand.send(OP["SC_RUN"], 7, 1, 0, 30, 30000, 2)[0] == ACK
    checked = stand.run_to_end(expect_spd=30)
    assert checked >= 80  # две паузы DELAY_MS 400 при тике 0.01 -- не меньше 80 наблюдений сценария
    assert _recs(stand.lines) == _slot_recs(1, 30, 30000, 1)
    assert _reg(stand.core, "TLM_SPD_PCT") == 80

    assert stand.send(OP["SC_RUN"], 7, 2, 0, 0, 0, 0)[0] == ACK
    stand.run_to_end()
    second = [r for r in _recs(stand.lines) if r[0] == 2]
    assert second == _slot_recs(2, 80, 25000, 0)


@pytest.mark.parametrize(
    ("p_accur_default", "spd_pct", "accel", "accur", "spd", "acc", "accur_val"),
    [
        pytest.param(0, 0, 0, 0, 80, 25000, 0, id="all-zero-defaults"),
        pytest.param(1, 100, 100, 0, 100, 100, 1, id="bounds-low-accel-accur0-takes-default-1"),
        pytest.param(1, 1, 50000, 1, 1, 50000, 0, id="bounds-high-accel-accur1-is-rough"),
        pytest.param(0, 0, 0, 2, 80, 25000, 1, id="accur2-is-high"),
    ],
)
def test_sc_run_accur_shift_and_bounds(p_accur_default, spd_pct, accel, accur, spd, acc, accur_val):
    """Сдвиг ``accur`` (0 -- умолчание, 1 -- ROUGH=0, 2 -- HIGH=1) и граничные значения диапазона.

    Сразу после ``_send`` -- ровно одна строка ``SC rec`` (запись 1, ``JOINT``) с ожидаемыми ``spd/acc/accur``
    (``accur`` в следе -- значение 0/1, не код провода), ``TLM_SPD_PCT`` == spd. До конца сценарий не гоним.
    НЕ доказывает: поведение записей 2+, влияние ACCEL/ACCUR на движение, прошивку.
    """
    stand = _Stand()
    stand.servo_on()
    stand.param_set("P_ACCUR_DEFAULT", p_accur_default)
    stand.load_slot()

    assert stand.send(OP["SC_RUN"], 7, 1, 0, spd_pct, accel, accur)[0] == ACK

    assert _recs(stand.lines) == [(1, 1, "JOINT", spd, acc, accur_val)]
    assert _reg(stand.core, "TLM_SPD_PCT") == spd


_NAK_RANGE = (NAK, E_RANGE, 1, R_APARAM)


@pytest.mark.parametrize(
    ("servo", "args", "expected"),
    [
        pytest.param(1, (7, 1, 0, 101, 0, 0), _NAK_RANGE, id="spd-101"),
        pytest.param(1, (7, 1, 0, 0, 99, 0), _NAK_RANGE, id="accel-99"),
        pytest.param(1, (7, 1, 0, 0, 50001, 0), _NAK_RANGE, id="accel-50001"),
        pytest.param(1, (7, 1, 0, 0, 0, 3), _NAK_RANGE, id="accur-3"),
        pytest.param(0, (7, 1, 0, 101, 0, 0), _NAK_RANGE, id="spd-101-servo-off-range-before-servo"),
        pytest.param(1, (7, 1, 0), (NAK, E_BAD_ARGC), id="old-argc-3"),
    ],
)
def test_sc_run_bad_args_nak_no_motion(servo, args, expected):
    """Состояние вне диапазона -- NAK ``E_RANGE [R_APARAM]``; старое число аргументов -- ``E_BAD_ARGC``.

    Без движения и без следов: поза, ``TLM_ACTIVITY``, ``TLM_SC_*``, ``TLM_DO_MASK`` не меняются 20 тиков,
    строк ``SC start`` / ``SC rec`` / ``CMD ... op=SC_RUN`` нет. При выключенном серво проверка состояния идёт
    раньше проверки серво (``E_RANGE``, не ``E_NO_SERVO``). При включённом серво следующий корректный
    ``SC_RUN`` принимается (робот не застрял). НЕ доказывает: прошивку, поведение при ``servo == 0`` для
    корректного состояния.
    """
    stand = _Stand()
    stand.set_servo(servo)
    stand.load_slot()

    def snapshot() -> tuple[list[int], int, int, int, int, int]:
        return (
            stand.core.read(REG["TLM_X"], 4),
            _reg(stand.core, "TLM_ACTIVITY"),
            _reg(stand.core, "TLM_SC_ID"),
            _reg(stand.core, "TLM_SC_TOTAL"),
            _reg(stand.core, "TLM_SC_DONE_N"),
            _reg(stand.core, "TLM_DO_MASK"),
        )

    before = snapshot()
    n0 = len(stand.lines)
    res = stand.send(OP["SC_RUN"], *args)
    assert res[: len(expected)] == expected
    for _ in range(20):
        stand.core.tick(0.01)

    assert snapshot() == before
    new_lines = stand.lines[n0:]
    forbidden = [line for line in new_lines if re.search(r"SC start|SC rec|CMD\b.*\bop=SC_RUN", line)]
    assert forbidden == []
    if servo:
        assert stand.send(OP["SC_RUN"], 7, 1, 0, 0, 0, 0)[0] == ACK


# ---------------------------------------------------------------------------
# f-g. e2e: перенос состояния через границу куска
# ---------------------------------------------------------------------------


def _long_stroke_expected_recs() -> list[Rec]:
    recs: list[Rec] = [(1, 1, "JOINT", 80, 25000, 0), (1, 2, "LINE", 30, 25000, 0)]
    for k in (2, 3, 4):
        recs += [(k, i, "LINE_PASS", 30, 25000, 0) for i in range(1, 27)]
        recs.append((k, 27, "LINE", 30, 25000, 0))
    recs += [(5, i, "LINE_PASS", 30, 25000, 0) for i in range(1, 18)]
    recs.append((5, 18, "LINE", 30, 25000, 0))
    recs.append((5, 19, "LINE", 100, 25000, 0))
    return recs


def test_long_stroke_speed_survives_every_boundary():
    """Штрих 100 точек (102 записи, 5 кусков): SPEED_PCT 30 держится на каждой границе, подъём -- 100.

    Куски 2-5 идут на ``spd=30`` (не на 80), последняя запись -- ``spd=100``; ``acc=25000 accur=0`` у всех
    102 строк. Действий ``SC act`` ровно два (SPEED_PCT 30 в куске 1, SPEED_PCT 100 в куске 5). НЕ доказывает:
    физическую скорость пера, контроллер, сглаживание LINE_PASS.
    """
    with E2eRig() as rig:
        report = rig.run(draw(STROKE100, frame="sheet", hand=1, rz=0.0, pen_down=0.0, pen_up=5.0), FRAMES)
        assert report.chunks == ((0, 2, 0), (2, 27, 27), (29, 27, 0), (56, 27, 27), (83, 19, 0))
        assert report.total == 102
        texts = _event_texts(rig)
        assert _ends(texts) == [(1, 2), (2, 27), (3, 27), (4, 27), (5, 19)]
        assert _recs(texts) == _long_stroke_expected_recs()
        assert _acts(texts) == [(1, 1, "SPEED_PCT", 30.0), (5, 18, "SPEED_PCT", 100.0)]
        assert rig.pose_wire() == (349.5, -80.0, -85.0, 0.0)


def _acc30_program(*, accur_back_to_rough: bool) -> Program:
    """30 точек на прямой; ACCEL 30000 после записи 1, ACCUR 1 после записи 2 (и ACCUR 0 после записи 3)."""
    steps: list[Move | Action] = [
        Move(point="p0", kind="JOINT"),
        Action(act="ACCEL", value=30000),
        Move(point="p1", kind="LINE"),
        Action(act="ACCUR", value=1),
    ]
    for j in range(2, 30):
        steps.append(Move(point=f"p{j}", kind="LINE"))
        if accur_back_to_rough and j == 2:
            steps.append(Action(act="ACCUR", value=0))
    name = "acc30z" if accur_back_to_rough else "acc30"
    return Program(name=name, steps=tuple(steps))


_ACC30_POINTS = {f"p{j}": Point(name=f"p{j}", x=300 + 5 * j, y=-100, z=-100, rz=0, hand=1) for j in range(30)}


def _rec_rows(sc_id: int, first: int, last: int, kind: str, spd: int, acc: int, accur: int) -> list[Rec]:
    return [(sc_id, i, kind, spd, acc, accur) for i in range(first, last + 1)]


@pytest.mark.parametrize("case", ["accur_high", "accur_back_to_rough"])
def test_accel_accur_cross_boundary(case):
    """ACCEL и ACCUR, поставленные в куске 1, видны в куске 2 полями ``acc=`` / ``accur=`` (spd -- умолчание).

    ``accur_high``: ACCUR 1 в куске 1 -> кусок 2 с ``accur=1``; кусок 2 на ``spd=80`` -- «0 -> умолчание» на пути
    клиента. ``accur_back_to_rough`` (``P_ACCUR_DEFAULT`` = 1): ACCUR 0 в куске 1 уходит кодом 1 (ROUGH) и в
    куске 2 даёт ``accur=0``, а не «не задано» (тогда было бы ``accur=1`` от параметра). НЕ доказывает: влияние
    ACCEL/ACCUR на движение, контроллер.
    """
    to_rough = case == "accur_back_to_rough"
    program = _acc30_program(accur_back_to_rough=to_rough)
    scenario = compile_program(program, _ACC30_POINTS, {}, WS_PARAMS)
    with E2eRig() as rig:
        if to_rough:
            bounded(lambda: rig.client.param_set("P_ACCUR_DEFAULT", 1))
        report = rig.run(scenario)
        assert report.chunks == ((0, 27, 0), (27, 3, 27))
        assert report.total == 30
        texts = _event_texts(rig)
        if to_rough:
            assert _acts(texts) == [(1, 1, "ACCEL", 30000.0), (1, 2, "ACCUR", 1.0), (1, 3, "ACCUR", 0.0)]
            assert _recs(texts) == (
                [(1, 1, "JOINT", 80, 25000, 1)]
                + _rec_rows(1, 2, 3, "LINE", 80, 30000, 1)
                + _rec_rows(1, 4, 27, "LINE", 80, 30000, 0)
                + _rec_rows(2, 1, 3, "LINE", 80, 30000, 0)
            )
        else:
            assert _acts(texts) == [(1, 1, "ACCEL", 30000.0), (1, 2, "ACCUR", 1.0)]
            assert _recs(texts) == (
                [(1, 1, "JOINT", 80, 25000, 0), (1, 2, "LINE", 80, 30000, 0)]
                + _rec_rows(1, 3, 27, "LINE", 80, 30000, 1)
                + _rec_rows(2, 1, 3, "LINE", 80, 30000, 1)
            )
            assert rig.pose_wire() == (445.0, -100.0, -100.0, 0.0)


# ---------------------------------------------------------------------------
# h. e2e: клиентский NAK без движения
# ---------------------------------------------------------------------------


def test_client_start_state_nak_no_motion():
    """``RobotClientV2.sc_run`` со стартовым состоянием вне диапазона: ``RobotNak`` и ни шагу движения.

    ``spd_pct`` 101 -> ``RobotNak(errno=3, reason=3)``; 0.2 с времени sim после NAK робот стоит в HOME,
    ``activity == 0``, строк ``SC start`` / ``SC rec`` нет. Затем ``sc_run`` с нулями доходит до ``SC end``
    (``spd=80 acc=25000 accur=0``). НЕ доказывает: прошивку, влияние ACCEL/ACCUR на движение.
    """
    with E2eRig() as rig:
        words = encode_scenario(rig.compile(return_slot(SLOT)), params=WS_PARAMS, round_step=0.1)
        bounded(lambda: rig.client.upload(words, 0))
        n0 = len(rig.core.events())

        with pytest.raises(RobotNak) as info:
            bounded(lambda: rig.client.sc_run(7, 1, 0, 101, 0, 0))
        assert info.value.errno == E_RANGE
        assert info.value.reason == R_APARAM

        t0 = rig.core.ticks()[-1].t
        rig.wait_tick(lambda t: t.t >= t0 + 0.2, timeout_s=10.0)
        window = [k for k in rig.core.ticks() if t0 < k.t <= t0 + 0.2]
        assert window
        assert all(k.activity == ACTIVITY_IDLE for k in window)
        assert all(k.pose == HOME_POSE for k in window)
        assert [t for t in _event_texts(rig, n0) if re.search(r"SC start|SC rec", t)] == []

        res = bounded(lambda: rig.client.sc_run(7, 1, 0, 0, 0, 0))
        bounded(lambda: rig.client.wait_done(res.seq), 15)
        rig.wait_event(r"SC end id=1 done_n=7(?!\d)", after=n0, timeout_s=10)
        texts = _event_texts(rig, n0)
        assert _ends(texts) == [(1, 7)]
        assert _recs(texts) == _slot_recs(1, 80, 25000, 0)
