"""Слепая приёмка T3.5: e2e «клиент v2 (RobotClientV2 + ModbusDevice) <-> sim v2 (SimRobotServer)».

Purpose:
    Доказать по проводу Modbus/TCP, что сценарии генераторов (рисование двумя
    кусками, возврат в слот, смена инструмента, CVT-задание), стоп, сторожевой
    таймер, поводок jog, перезапуск sim с зеркалом и ходы нулевой длины
    наблюдаются: события sim (`trace_sc`) и снимки тиков, а не только
    `TLM_SC_DONE_N`.

Что весь файл НЕ доказывает:
    - поведение настоящего контроллера (sim — модель; случаи нулевой длины на
      контроллере не изучены: OPEN_QUESTIONS T3.4 п.4-5, Ф7);
    - сглаживание LINE_PASS, разгон (ACCEL) и точность (ACCUR): sim их только
      хранит;
    - время торможения HARD-стопа.

Окна меряются во времени sim (`Tick.t`, штампы событий), не по стенным часам;
стенное время — только верхний дедлайн блокирующих вызовов. Ожидаемые значения —
литералы брифа T3.5, не выведенные из кода под проверкой.
"""

from __future__ import annotations

import re

import pytest

from Services.robot_comm import ROBOT_AVAILABLE
from Services.robot_comm.core.client_v2 import SyncReport
from Services.robot_comm.core.params_v2 import PARAM_ID, PARAMS
from Services.robot_comm.core.protocol_v2 import ERR
from Services.robot_comm.errors import RobotAborted, RobotCommandError
from Services.robot_comm.programs import FrameDef, Point
from Services.robot_comm.programs.generators import draw, return_slot, toolchange
from Services.robot_comm.tests.e2e_rig_v2 import E2eRig, bounded, pulse
from Services.vfd_comm.core.registers import (
    REG_CMD_DIR,
    REG_CMD_FREQ,
    REG_CMD_RUN,
    REG_ST_BASE,
    REG_VFD_FLAG,
)

__all__: list[str] = []

pytestmark = pytest.mark.skipif(not ROBOT_AVAILABLE, reason="Services.robot_comm недоступен")

# ---------------------------------------------------------------------------
# Фикстуры брифа (литералы)
# ---------------------------------------------------------------------------

SHEET = FrameDef(
    name="sheet",
    origin=(300, -100, -100),
    on_x=(400, -100, -100),
    in_plane=(300, 0, -100),
)
FRAMES = {"sheet": SHEET}

_LI = (
    ((0, 0), (8, 40), (25, 40), (25, 0)),
    ((35, 40), (35, 0), (55, 40)),
    ((55, 40), (55, 0)),
)


def _shift(strokes: tuple, dx: int) -> tuple:
    return tuple(tuple((x + dx, y) for x, y in stroke) for stroke in strokes)


LI3 = _LI + _shift(_LI, 60) + _shift(_LI, 120)

SLOT = Point(name="slot", x=350, y=-150, z=-90, rz=10, hand=1)
HOME = Point(name="home", x=300, y=-210, z=-40, rz=-100, hand=1)


def _lib_point(name: str, x: float, y: float, z: float) -> Point:
    return Point(name=name, x=x, y=y, z=z, rz=0, hand=1)


LIB = {
    "t1_over": _lib_point("t1_over", 400, 100, -20),
    "t1_pick": _lib_point("t1_pick", 400, 100, -80),
    "t1_exit": _lib_point("t1_exit", 400, 160, -80),
    "t2_over": _lib_point("t2_over", 400, -100, -20),
    "t2_pick": _lib_point("t2_pick", 400, -100, -80),
    "t2_exit": _lib_point("t2_exit", 400, -40, -80),
}

_KIND = {"J": "JOINT", "L": "LINE", "P": "LINE_PASS"}
_KINDS_CHUNK1 = [_KIND[c] for c in "J L P P L L L L P L L L L L L L P P L L L L P L L L L".split()]
_KINDS_CHUNK2 = [_KIND[c] for c in "L L L P P L L L L P L L L L L".split()]
_SPD_CHUNK1 = [
    int(v) for v in ("80 30 30 30 30 100 100 30 30 30 100 30 30 100 100 30 30 30 30 100 100 30 30 30 100 30 30").split()
]
_SPD_CHUNK2_FROM3 = [int(v) for v in "30 30 30 30 100 100 30 30 30 100 30 30 100".split()]

_REC = re.compile(r"SC rec id=(\d+) i=(\d+) kind=(\w+) spd=(\d+)")
_ACT = re.compile(r"SC act id=(\d+) i=(\d+) act=(\w+) val=(-?\d+(?:\.\d+)?)")


# ---------------------------------------------------------------------------
# Помощники разбора событий и тиков (оракул — события и тики)
# ---------------------------------------------------------------------------


def _recs(events: list, sc_id: int, after: int = 0) -> list[tuple[int, float, int, str, int]]:
    """Строки `SC rec` куска: (индекс события, штамп, i, kind, spd)."""
    out = []
    for idx in range(after, len(events)):
        t, text = events[idx]
        m = _REC.search(text)
        if m and int(m.group(1)) == sc_id:
            out.append((idx, t, int(m.group(2)), m.group(3), int(m.group(4))))
    return out


def _acts(events: list, sc_id: int, after: int = 0) -> list[tuple[int, float, int, str, float]]:
    """Строки `SC act` куска: (индекс события, штамп, i, act, val)."""
    out = []
    for idx in range(after, len(events)):
        t, text = events[idx]
        m = _ACT.search(text)
        if m and int(m.group(1)) == sc_id:
            out.append((idx, t, int(m.group(2)), m.group(3), float(m.group(4))))
    return out


def _find_act(events: list, sc_id: int, i: int, act: str, after: int = 0) -> tuple[int, float, float]:
    hits = [a for a in _acts(events, sc_id, after) if a[2] == i and a[3] == act]
    assert len(hits) == 1, f"SC act id={sc_id} i={i} act={act}: найдено {len(hits)}"
    idx, t, _i, _act, val = hits[0]
    return idx, t, val


def _count(events: list, pattern: str, after: int = 0) -> int:
    rx = re.compile(pattern)
    return sum(1 for _t, text in events[after:] if rx.search(text))


def _pose(tick) -> tuple[float, float, float, float]:
    return tuple(float(v) for v in tick.pose)  # type: ignore[return-value]


def _ticks_at(ticks: list, stamp: float) -> list:
    got = [k for k in ticks if k.t == stamp]
    assert got, f"нет тика со штампом t={stamp!r}"
    return got


def _bit(mask: int, bit: int) -> int:
    return (int(mask) >> bit) & 1


def _check_do(events: list, ticks: list, sc_id: int, i: int, act: str, pose: tuple) -> float:
    """DO по п.3: тик со штампом строки `act` — бит изменён, поза = точка записи."""
    _idx, t_a, val = _find_act(events, sc_id, i, act)
    bit = int(val) - 1
    want = 1 if act == "DO_ON" else 0
    for k in _ticks_at(ticks, t_a):
        assert _bit(k.do_mask, bit) == want, f"{act} i={i}: do_mask={k.do_mask} на t={t_a}"
        assert _pose(k) == pytest.approx(pose, abs=1e-6)
    if act == "DO_ON":
        for k in ticks:
            if k.t < t_a:
                assert _bit(k.do_mask, bit) == 0, f"бит {bit} уже 1 на t={k.t} < {t_a}"
    return t_a


def _check_delay(events: list, ticks: list, sc_id: int, i: int, d_ms: int) -> float:
    """Пауза DELAY_MS по п.3. Возвращает held (с, время sim)."""
    idx_a, t_a, val = _find_act(events, sc_id, i, "DELAY_MS")
    assert val == d_ms
    end_rx = re.compile(rf"SC (?:rec|end) id={sc_id}(?!\d)")
    t_b = None
    for idx in range(idx_a + 1, len(events)):
        if end_rx.search(events[idx][1]):
            t_b = events[idx][0]
            break
    assert t_b is not None, f"после DELAY_MS i={i} нет следующей SC rec/SC end"
    held = t_b - t_a
    window = [k for k in ticks if t_a < k.t <= t_b]
    assert window, "в окне паузы нет тиков"
    max_dt = max(k.dt for k in window)
    assert d_ms / 1000 - 1e-9 <= held <= d_ms / 1000 + max_dt + 1e-9, (
        f"DELAY {d_ms} мс i={i}: held={held!r}, max_dt={max_dt!r}"
    )
    pose_a = _pose(_ticks_at(ticks, t_a)[0])
    inner = [k for k in ticks if t_a < k.t < t_b]
    assert inner, "внутри паузы нет тиков"
    for k in inner:
        assert k.moving == 0, f"движение внутри паузы на t={k.t}"
        assert _pose(k) == pose_a, f"поза меняется внутри паузы на t={k.t}"
    return held


def _last_change(ticks: list, field: str, t_max: float) -> int:
    """Индекс последнего тика с t <= t_max, где `field` отличается от предыдущего тика."""
    found = -1
    for n in range(1, len(ticks)):
        if ticks[n].t <= t_max and getattr(ticks[n], field) != getattr(ticks[n - 1], field):
            found = n
    assert found >= 1, f"нет смены {field} до t={t_max!r}"
    return found


def _ticks_since(rig, stamp: float, count: int) -> list:
    """Ждёт, пока наберётся `count` тиков с t >= stamp; возвращает первые `count`."""

    def _enough(_tick) -> bool:
        return sum(1 for k in rig.core.ticks() if k.t >= stamp) >= count

    rig.wait_tick(_enough, timeout_s=10)
    return [k for k in rig.core.ticks() if k.t >= stamp][:count]


# ---------------------------------------------------------------------------
# a, b. Рисование двумя кусками
# ---------------------------------------------------------------------------


def _draw_li3():
    return draw(LI3, frame="sheet", hand=1, rz=0.0, pen_down=0.0, pen_up=5.0)


def test_draw_two_chunks():
    """Рисование LI3 -> 42 записи двумя кусками (27 + 15): виды, скорость, итог.

    НЕ доказывает: контроллер, сглаживание LINE_PASS, разгон/точность; скорость
    записей 1-2 куска 2 — тест b.
    """
    with E2eRig() as rig:
        report = rig.run(_draw_li3(), FRAMES)
        assert report.chunks == ((0, 27, 0), (27, 15, 27))
        assert report.total == 42
        events = rig.core.events()
        assert _count(events, r"SC end id=1 done_n=27(?!\d)") == 1
        assert _count(events, r"SC end id=2 done_n=15(?!\d)") == 1

        rec1 = _recs(events, 1)
        assert [r[2] for r in rec1] == list(range(1, 28))
        assert [r[3] for r in rec1] == _KINDS_CHUNK1
        assert [r[4] for r in rec1] == _SPD_CHUNK1

        rec2 = _recs(events, 2)
        assert [r[2] for r in rec2] == list(range(1, 16))
        assert [r[3] for r in rec2] == _KINDS_CHUNK2
        assert [r[4] for r in rec2 if r[2] >= 3] == _SPD_CHUNK2_FROM3

        assert rig.pose_wire() == (475.0, -100.0, -85.0, 0.0)
        assert rig.read("TLM_DO_MASK") == [0]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "T3.9: состояние SPEED_PCT не переходит через границу куска "
        "(SC_RUN без стартового состояния; protocol-spec §7.2 п.5, §7.4)"
    ),
)
def test_draw_speed_survives_chunk_boundary():
    """Скорость переезда (запись 27: SPEED_PCT 100) переходит в кусок 2.

    Сегодня ожидаемо красный: sim заводит кусок с P_SPD_DEFAULT 80. После T3.9
    strict xfail упадёт, и метку снимает T3.9. НЕ доказывает: контроллер.
    """
    with E2eRig() as rig:
        rig.run(_draw_li3(), FRAMES)
        rec2 = _recs(rig.core.events(), 2)
        assert [r[4] for r in rec2 if r[2] in (1, 2)] == [100, 100]


# ---------------------------------------------------------------------------
# c. Возврат в слот: DO и паузы
# ---------------------------------------------------------------------------


def test_return_slot_do_and_delay():
    """return_slot: DO_ON на записи 2, DO_OFF на записи 6, две паузы DELAY 400.

    НЕ доказывает: контроллер, реальный захват; sim двигает DO-маску, но не
    физический исполнитель.
    """
    with E2eRig() as rig:
        report = rig.run(return_slot(SLOT))
        assert report.total == 7
        events = rig.core.events()
        ticks = rig.core.ticks()
        pose = (350.0, -150.0, -90.0, 10.0)
        pose_off = (450.0, -150.0, -90.0, 10.0)

        t_on = _check_do(events, ticks, 1, 2, "DO_ON", pose)
        t_off = _check_do(events, ticks, 1, 6, "DO_OFF", pose_off)
        between = [k for k in ticks if t_on <= k.t < t_off]
        assert between
        for k in between:
            assert _bit(k.do_mask, 0) == 1, f"бит 0 не 1 между DO_ON и DO_OFF на t={k.t}"

        _check_delay(events, ticks, 1, 3, 400)
        _check_delay(events, ticks, 1, 7, 400)

        assert rig.read("TLM_DO_MASK") == [0]
        assert rig.read("TLM_SC_DONE_N") == [7]


# ---------------------------------------------------------------------------
# d. Смена инструмента: ACCUR / ACCEL / DELAY
# ---------------------------------------------------------------------------


def test_toolchange_accur_accel_delay():
    """toolchange: ACCUR и DELAY_MS 1000 приняты sim; ACCEL приходит из draw(accel=...).

    sim ACCEL/ACCUR только хранит (разгон и точность не моделирует): тест
    доказывает приём действий sim, не влияние на движение. НЕ доказывает
    контроллер.
    """
    with E2eRig() as rig:
        rig.run(toolchange(1, 2, LIB))
        events = rig.core.events()
        got = [(a[2], a[3], a[4]) for a in _acts(events, 1)]
        assert got == [
            (1, "ACCUR", 1),
            (2, "DELAY_MS", 1000),
            (3, "ACCUR", 0),
            (5, "ACCUR", 1),
            (6, "DELAY_MS", 1000),
            (7, "ACCUR", 0),
        ]
        ticks = rig.core.ticks()
        for i in (2, 6):
            held = _check_delay(events, ticks, 1, i, 1000)
            assert 1.0 - 1e-9 <= held
        assert rig.pose_wire() == (400.0, -40.0, -80.0, 0.0)

        n0 = len(events)
        rig.run(
            draw(
                (((0, 0), (20, 0)),),
                frame="sheet",
                hand=1,
                rz=0.0,
                pen_down=0.0,
                pen_up=5.0,
                accel=30000,
            ),
            FRAMES,
        )
        events2 = rig.core.events()
        assert _count(events2, r"SC act id=1 i=2 act=ACCEL val=30000(?!\d)", after=n0) == 1


# ---------------------------------------------------------------------------
# e. Стоп посреди сценария
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("level", ["hard", "soft"])
def test_stop_mid_scenario(level):
    """Стоп посреди сценария (HARD: DO не трогает; SOFT: останов на EXACT-точке).

    HARD: стоп DO не трогает — свойство sim T2.3, на контроллере не проверено.
    НЕ доказывает: время торможения HARD, поведение контроллера.
    """
    with E2eRig() as rig:
        if level == "hard":
            p = rig.start_run(return_slot(SLOT, grip_delay_ms=3000))
            rig.wait_event(r"SC act id=1 i=2 act=DO_ON")
            bounded(lambda: rig.client.stop(2))
            with pytest.raises(RobotAborted):
                p.wait(10)
            assert rig.read("TLM_SC_DONE_N") == [2]
            assert _bit(rig.read("TLM_DO_MASK")[0], 0) == 1
            _idx, stamp, _text = rig.wait_event(r"ERR .*E_ABORTED")
            events = rig.core.events()
            idx_err = next(n for n, (_t, tx) in enumerate(events) if re.search(r"ERR .*E_ABORTED", tx))
            assert _count(events, r"SC rec ", after=idx_err + 1) == 0
            after = _ticks_since(rig, stamp, 11)
            assert len({_pose(k) for k in after}) == 1
            assert rig.read("TLM_ACTIVITY") == [0]
        else:
            bounded(lambda: rig.client.param_set("P_SPD_L", 300))
            p = rig.start_run(_draw_li3(), FRAMES)
            rig.wait_event(r"SC rec id=1 i=3 kind=LINE_PASS")
            bounded(lambda: rig.client.stop(1))
            with pytest.raises(RobotAborted):
                p.wait(10)
            assert rig.pose_wire() == (325.0, -100.0, -100.0, 0.0)
            assert rig.read("TLM_SC_DONE_N") == [5]


# ---------------------------------------------------------------------------
# f. Сторожевой таймер
# ---------------------------------------------------------------------------


def test_watchdog_silence_stops_belt():
    """ПК молчит дольше 1000 мс -> сторож останавливает ленту и обрывает сценарий.

    Фаза A: пульс держит сторож; B: молчание -> E_WDG_TIMEOUT, лента стоит;
    C: сторож обрывает идущий сценарий (RobotCommandError, не RobotAborted).
    НЕ доказывает: контроллер; жёсткие стенные границы (окна — время sim).
    """
    with E2eRig() as rig:
        bounded(lambda: rig.client.param_set("P_WDG_TIMEOUT_MS", 1000))
        bounded(
            lambda: rig.device.transaction(
                [
                    ("w", REG_CMD_FREQ, 5000),
                    ("w", REG_CMD_DIR, 0),
                    ("w", REG_CMD_RUN, 1),
                    ("w", REG_VFD_FLAG, 1),
                ]
            )
        )
        t_w = rig.core.ticks()[-1].t
        rig.wait_tick(lambda t: t.t >= t_w + 0.05)
        assert bounded(lambda: rig.device.read_registers(REG_ST_BASE, 2)) == [1, 5000]

        # Фаза A: пульс держит сторож.
        t0 = rig.core.ticks()[-1].t
        with pulse(rig.client.kick_heartbeat, 0.1) as p:
            arm = rig.wait_tick(lambda t: t.t > t0 and t.wdg_state == 1)
            end = rig.wait_tick(lambda t: t.t >= arm.t + 2.0, timeout_s=10)
        window = [k for k in rig.core.ticks() if arm.t <= k.t <= end.t]
        assert window
        for k in window:
            assert k.wdg_state == 1, f"сторож не взведён на t={k.t}"
            assert k.belt_mm_s > 0, f"лента стоит на t={k.t}"
        assert p.errors == []

        # Фаза B: ПК молчит.
        trip = rig.wait_tick(lambda t: t.t > end.t and t.wdg_state == 2, timeout_s=5)
        ticks = rig.core.ticks()
        n_hb = _last_change(ticks, "hb_pc", trip.t)
        t_hb = ticks[n_hb].t
        dt_next = ticks[n_hb + 1].dt
        gap = trip.t - t_hb
        assert 1.000 < gap <= 1.000 + trip.dt + dt_next + 1e-9, f"gap={gap!r}"
        for k in ticks:
            if k.t >= trip.t:
                assert k.belt_mm_s == 0, f"лента едет после срабатывания на t={k.t}"
        assert bounded(lambda: rig.device.read_registers(REG_ST_BASE, 1)) == [0]
        errors = bounded(rig.client.poll_errors)
        assert len(errors) == 1
        assert errors[0].errno == ERR["E_WDG_TIMEOUT"]
        assert rig.read("TLM_SERVO") == [1]

        # Фаза C: сторож обрывает сценарий.
        n0 = len(rig.core.events())
        with pulse(rig.client.kick_heartbeat, 0.1):
            run = rig.start_run(toolchange(1, 2, LIB))
            rig.wait_event(r"SC rec id=1 i=1 kind=", after=n0, timeout_s=10)
        rig.wait_event(r"ERR .*E_WDG_TIMEOUT", after=n0, timeout_s=5)
        with pytest.raises(RobotCommandError) as info:
            run.wait(10)
        assert type(info.value) is RobotCommandError
        assert info.value.errno == ERR["E_WDG_TIMEOUT"]


# ---------------------------------------------------------------------------
# g. Поводок jog
# ---------------------------------------------------------------------------


def test_jog_lease():
    """JOG_CONT живёт, пока пульс продлевает поводок; без пульса DONE через 1.0 с.

    НЕ доказывает: контроллер; точность скорости jog (допуск — шаг тика и
    провода 0.1 мм).
    """
    with E2eRig() as rig:
        bounded(lambda: rig.client.param_set("P_JOG_LEASE_MS", 1000))
        n0 = len(rig.core.events())
        with pulse(rig.client.jog_lease, 0.1):
            res = bounded(lambda: rig.client.jog_cont(1, 50))
            _, t_cmd, _ = rig.wait_event(rf"CMD seq={res.seq} op=JOG_CONT", after=n0)
            rig.wait_tick(lambda t: t.t >= t_cmd + 1.5, timeout_s=10)
        bounded(lambda: rig.client.wait_done(res.seq), 5)
        _, t_done, _ = rig.wait_event(rf"DONE seq={res.seq} op=JOG_CONT", after=n0)
        assert t_done - t_cmd > 1.5

        ticks = rig.core.ticks()
        n_lease = _last_change(ticks, "jog_lease", t_done)
        t_lease = ticks[n_lease].t
        dt_next = ticks[n_lease + 1].dt
        done_tick = _ticks_at(ticks, t_done)[0]
        cmd_tick = _ticks_at(ticks, t_cmd)[0]
        gap = t_done - t_lease
        assert 1.000 < gap <= 1.000 + done_tick.dt + dt_next + 1e-9, f"gap={gap!r}"

        x, y, z, rz = _pose(done_tick)
        assert (y, z, rz) == pytest.approx((-210.0, -40.0, -100.0), abs=1e-6)
        assert x > 300.0
        tol = 50 * (cmd_tick.dt + done_tick.dt) + 0.1
        assert abs((x - 300.0) - 50 * (t_done - t_cmd)) <= tol

        after = _ticks_since(rig, t_done, 11)
        assert len({_pose(k) for k in after}) == 1

        # Контроль без поводка: ход X- гаснет через 1.0 с.
        n1 = len(rig.core.events())
        res2 = bounded(lambda: rig.client.jog_cont(2, 50))
        _, t_cmd2, _ = rig.wait_event(rf"CMD seq={res2.seq} op=JOG_CONT", after=n1)
        bounded(lambda: rig.client.wait_done(res2.seq), 5)
        _, t_done2, _ = rig.wait_event(rf"DONE seq={res2.seq} op=JOG_CONT", after=n1)
        span = [k for k in rig.core.ticks() if t_cmd2 <= k.t <= t_done2]
        max_dt = max(k.dt for k in span)
        assert 1.000 < t_done2 - t_cmd2 <= 1.000 + 2 * max_dt + 1e-9


# ---------------------------------------------------------------------------
# h. CVT
# ---------------------------------------------------------------------------


def test_cvt_job_tracks_and_places():
    """CVT-задание: захват движущегося объекта и укладка; промах вне кольца.

    Допущение A: лента sim по умолчанию едет по +Y (v1-скорость enc_rate=7, ось
    P_BELT_DIR 1). НЕ доказывает: контроллер, реальную калибровку ленты.
    """
    with E2eRig() as rig:
        lo, hi = rig.read("TLM_ENC", 2)
        ecap = lo | hi << 16
        res = bounded(lambda: rig.client.cvt_job(ecap, 300, -150, -100, 3, 450, -300, -90, -100))
        bounded(lambda: rig.client.wait_done(res.seq), 15)
        assert rig.pose_wire() == (450.0, -300.0, -90.0, -100.0)
        jobs = rig.core.jobs()
        assert len(jobs) == 1
        assert jobs[0]["index"] == 1
        assert jobs[0]["x_mm"] == 300.0
        assert jobs[0]["y_mm"] == -150.0
        assert jobs[0]["ecap"] == ecap
        grips = [re.search(r"CVT grip seq=\d+ x=(-?[\d.]+) y=(-?[\d.]+)", text) for _t, text in rig.core.events()]
        grips = [m for m in grips if m]
        assert len(grips) == 1
        assert float(grips[0].group(1)) == 300.0
        assert float(grips[0].group(2)) > -150.0

        # Промах: pick вне кольца 120..500 мм.
        miss0 = rig.read("TLM_MISS_COUNT")[0]
        res2 = bounded(lambda: rig.client.cvt_job(ecap, 50, 0, -100, 3, 450, -300, -90, -100))
        with pytest.raises(RobotCommandError) as info:
            bounded(lambda: rig.client.wait_done(res2.seq), 15)
        assert info.value.errno == ERR["E_ZONE_TRIP"]
        assert rig.read("TLM_MISS_COUNT")[0] == miss0 + 1
        assert _count(rig.core.events(), r"CVT miss ") == 1


# ---------------------------------------------------------------------------
# i. Перезапуск sim с зеркалом
# ---------------------------------------------------------------------------


def test_restart_keeps_mirror():
    """Перезапуск контроллера: зеркало параметров на проводе сохраняется.

    После restart() повторная sync_params не шлёт ничего (SyncReport(0, False, 7)),
    P_SPD_DEFAULT 55 действует в новом сценарии; restart(keep_regs=False) стирает
    эпоху. НЕ доказывает: поведение энергонезависимой памяти настоящего контроллера.
    """
    with E2eRig() as rig:
        values = {name: PARAMS[PARAM_ID[name]]["default"] for name in PARAM_ID if name != "P_CONFIG_EPOCH"}
        values["P_SPD_DEFAULT"] = 55
        rep = bounded(lambda: rig.client.sync_params(values, 7))
        assert rep.sent > 0

        rig.restart()
        assert bounded(lambda: rig.client.sync_params(values, 7)) == SyncReport(0, False, 7)
        assert bounded(lambda: rig.client.param_get("P_SPD_DEFAULT")) == 55
        assert rig.read("TLM_CFG_EPOCH") == [7]
        assert rig.read("TLM_SPD_PCT") == [55]

        rig.run(return_slot(SLOT))
        assert _count(rig.core.events(), r"SC rec id=1 i=1 kind=JOINT spd=55(?!\d)") == 1

        # Контроль: restart без регистров стирает зеркало.
        rig.restart(keep_regs=False)
        assert rig.read("TLM_CFG_EPOCH") == [0]
        assert bounded(lambda: rig.client.sync_params(values, 7)).sent > 0


# ---------------------------------------------------------------------------
# j. Ходы нулевой длины
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", ["approach_eq_first", "stroke_under_quantum", "shift_under_quantum"])
def test_zero_length_moves(case):
    """Ход нулевой длины завершается штатно, sim не падает (исключения тика — на выходе из E2eRig).

    На контроллере эти случаи не изучены (OPEN_QUESTIONS T3.4 п.4-5, Ф7); тест
    фиксирует поведение sim после T2.5, не контроллера.
    """
    with E2eRig() as rig:
        if case == "approach_eq_first":
            gp = toolchange(1, 2, LIB, approach=LIB["t1_exit"])
            total, final = 9, (400.0, -40.0, -80.0, 0.0)
        elif case == "stroke_under_quantum":
            gp = draw(
                (((0, 0), (0.04, 0), (20, 0)),),
                frame="sheet",
                hand=1,
                rz=0.0,
                pen_down=0.0,
                pen_up=5.0,
            )
            total, final = 5, (320.0, -100.0, -85.0, 0.0)
        else:
            gp = return_slot(SLOT, push_dx_mm=0.04)
            total, final = 7, (350.0, -150.0, -90.0, 10.0)

        report = rig.run(gp, FRAMES)
        assert report.total == total
        events = rig.core.events()
        assert _count(events, rf"SC end id=1 done_n={total}(?!\d)") == 1
        assert len(_recs(events, 1)) == total
        assert rig.pose_wire() == final

        if case == "approach_eq_first":
            rec = [r for r in _recs(events, 1) if r[2] == 2]
            assert len(rec) == 1 and rec[0][3] == "LINE"
            _idx, t_act, val = _find_act(events, 1, 2, "ACCUR")
            assert val == 1
            assert rec[0][1] != t_act
        elif case == "stroke_under_quantum":
            rec = [r for r in _recs(events, 1) if r[2] == 3]
            assert len(rec) == 1 and rec[0][3] == "LINE_PASS"
        else:
            _check_do(events, rig.core.ticks(), 1, _off_index(events), "DO_OFF", final)


def test_zero_length_joint_to_current_pose():
    """JOINT-ход в точку, где робот уже стоит, завершается штатно (фикс T2.5).

    Сначала return_slot(SLOT, home=HOME) приводит робота в HOME; затем
    toolchange(1, 2, LIB, approach=HOME) начинается с JOINT в HOME - JOINT
    нулевой длины. Раньше это роняло ядро sim; выход из E2eRig проверяет, что
    исключений тика нет. НЕ доказывает: поведение прошивки контроллера на JOINT
    нулевой длины (Ф7).
    """
    with E2eRig() as rig:
        rig.run(return_slot(SLOT, home=HOME))
        assert rig.pose_wire() == (300.0, -210.0, -40.0, -100.0)

        n0 = len(rig.core.events())
        rig.run(toolchange(1, 2, LIB, approach=HOME))
        events = rig.core.events()
        assert rig.read("TLM_SC_DONE_N") == [9]
        first = _recs(events, 1, after=n0)[0]
        assert (first[2], first[3]) == (1, "JOINT")
        assert rig.pose_wire() == (400.0, -40.0, -80.0, 0.0)


def _off_index(events: list) -> int:
    """Номер записи, на которой исполнен DO_OFF (из строки события)."""
    hits = [a for a in _acts(events, 1) if a[3] == "DO_OFF"]
    assert len(hits) == 1
    return hits[0][2]
