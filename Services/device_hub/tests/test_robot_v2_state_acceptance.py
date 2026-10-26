"""Слепая приёмка T5.3f f1-T: ``RobotState`` / ``RobotDriverV2.state`` по таблице переходов и инвариантам I1–I8.

Purpose:
    Оракул — ``plans/robot-protocol-v2/tasks/T5.3f.state-table.md`` (таблица переходов, I1–I8, API, контракты).
    Код драйвера при написании не читался. Ожидаемые значения — литералы оракула.

    Два слоя:
    * красные до f1 — переходы ``RobotState`` напрямую (``_api()`` импортирует имена ВНУТРИ теста, сбор файла
      на базе проходит, тест падает ``AttributeError`` на ``RobotState`` / ``state``);
    * ``# characterization`` — ответы ``drv.call(op, args)``: зелёные на базе и обязаны остаться зелёными после f1.

Public API:
    Только тесты ``test_*``.

Stability: lite
"""

from __future__ import annotations

import ast
import dataclasses
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from multiprocess_framework.modules.base_manager import open_scope

from Services.device_hub.registry.entry import DeviceEntry
from Services.robot_comm.core.protocol_v2 import REG
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.programs import Move, Point, Program

# Тексты отказов (оракул, строка 7)
T_STOP = "драйвер робота останавливается"
T_PROGRAM = "робот занят программой"
T_JOG = "робот в режиме jog"
T_JOB = "робот выполняет задание"
T_NOLINK = "нет связи с роботом"
T_SYNC = "идёт синхронизация параметров"

_QUEUE_MAXLEN = 8
_CLEAN_LATCH = (0, False, None, 0)  # «сброс защёлки» (оракул, строка 35)
_JOG_ARGS = {"dir": 1, "spd": 20}


def _err(message: str) -> dict:
    return {"status": "error", "message": message}


# --------------------------------------------------------------------------------------------------
# Помощники слоя состояния
# --------------------------------------------------------------------------------------------------


def _api() -> SimpleNamespace:
    """Имена API f1 — внутри вызова: на базе падает ``AttributeError`` в теле теста, а не при сборе."""
    from Services.device_hub.drivers import robot_driver_v2 as module

    return SimpleNamespace(
        RobotDriverV2=module.RobotDriverV2,
        RobotState=module.RobotState,
        RobotStateView=module.RobotStateView,
        JogView=module.JogView,
        JogRun=module._JogRun,
    )


class _Clock:
    """Управляемые часы объекта ``clock=``: ``t`` задаёт тест, ``calls`` считает вызовы."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = t
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        return self.t


class _Counter:
    """Вызываемое ``connected`` / ``budget``: возвращает ``value``, считает вызовы."""

    def __init__(self, value: Any) -> None:
        self.value = value
        self.calls = 0

    def __call__(self) -> Any:
        self.calls += 1
        return self.value


def _new(clock: _Clock | None = None) -> Any:
    return _api().RobotState(clock=clock or _Clock(), queue_maxlen=_QUEUE_MAXLEN)


def _run(seq: int = 7) -> Any:
    return _api().JogRun(seq=seq)


def _latch(view: Any) -> tuple:
    return (view.latch_level, view.latch_failed, view.latch_value, view.latch_attempts)


def _far_deadline() -> float:
    return time.monotonic() + 10


def _stopped(st: Any) -> None:
    """Останов по оракулу (контракт ``admit_launch`` строка 2): ``request_stop_begin`` + ``process_stop_plan``."""
    st.request_stop_begin()
    st.process_stop_plan(lambda: False)


def _program(st: Any) -> None:
    assert st.admit_launch(lambda: True) is None


def _job(st: Any) -> None:
    job = ("job", "owner")
    st.enqueue_job(job)
    assert st.take_next_action() == (None, job)


def _sync(st: Any) -> None:
    assert st.begin_sync() is True


def _jog_starting(st: Any) -> None:
    assert st.jog_hold_admit() == (None, None)


def _jog_held(st: Any) -> Any:
    run = _run()
    st.jog_started(run)
    return run


def _jog_stopping(st: Any) -> None:
    run = _jog_held(st)
    assert st.jog_release_begin() is run


def _dirty_latch(st: Any) -> tuple:
    """Грязная защёлка переходами; возвращает её значение (не равно сбросу)."""
    st.stop_written(3, None)
    st.stop_write_failed()
    assert st.next_stop_attempt(_far_deadline(), _Counter(1.0)) == 1
    before = _latch(st.view())
    assert before != _CLEAN_LATCH
    return before


# Хозяева движения / состояния: имя -> построитель
_OWNERS: dict[str, Callable[[Any], None]] = {
    "program": _program,
    "job": _job,
    "jog_starting": _jog_starting,
    "jog_held": lambda st: _jog_held(st),
    "jog_stopping": _jog_stopping,
}


def _owners_count(view: Any) -> int:
    jog = view.jog is not None or view.jog_starting or view.jog_stopping
    return int(view.program_active) + int(view.job_active) + int(jog)


# --------------------------------------------------------------------------------------------------
# REDS: контракты переходов (таблица «Контракты переходов», построчно)
# --------------------------------------------------------------------------------------------------


def c_fresh_view() -> None:
    v = _new().view()
    assert v.program_active is False
    assert v.has_prog_handle is False
    assert v.job_active is False
    assert v.jog is None
    assert v.jog_starting is False
    assert v.jog_stopping is False
    assert v.last_hold == 0.0
    assert v.syncing is False
    assert v.stopping is False
    assert v.shutdown is False
    assert v.stop_level == 0
    assert (v.latch_level, v.latch_failed, v.latch_value, v.latch_attempts) == (0, False, None, 0)
    assert v.echo_checked is None
    assert v.stop_unconfirmed is False
    assert v.stop_unconfirmed_text is None
    assert v.own_stops == ()
    assert v.job_queue == ()
    assert v.return_queue == ()
    assert (v.returns_done, v.returns_failed) == (0, 0)


def c_admit_launch_fresh() -> None:
    st = _new()
    connected = _Counter(True)
    assert st.admit_launch(connected) is None
    assert connected.calls == 1
    v = st.view()
    assert v.program_active is True
    assert _latch(v) == _CLEAN_LATCH


def c_admit_launch_stopping() -> None:
    st = _new()
    st.request_stop_begin()
    st.process_stop_plan(lambda: False)
    before = st.view()
    connected = _Counter(True)
    assert st.admit_launch(connected) == _err(T_STOP)
    assert connected.calls == 0
    assert st.view() == before


def c_admit_launch_program_busy() -> None:
    st = _new()
    _program(st)
    before = st.view()
    assert st.admit_launch(lambda: True) == _err(T_PROGRAM)
    assert st.view() == before


def c_admit_launch_syncing() -> None:
    st = _new()
    assert st.begin_sync() is True
    before = st.view()
    assert st.admit_launch(lambda: True) == _err(T_SYNC)
    assert st.view() == before


def c_admit_launch_no_link() -> None:
    st = _new()
    before = st.view()
    assert st.admit_launch(lambda: False) == _err(T_NOLINK)
    assert st.view() == before


def c_jog_hold_check_fresh() -> None:
    clock = _Clock()
    st = _new(clock)
    before = st.view()
    assert st.jog_hold_check() is None
    assert clock.calls == 0
    assert st.view() == before


def c_jog_hold_check_hold() -> None:
    clock = _Clock(1.0)
    st = _new(clock)
    st.jog_started(_run(7))
    clock.t = 1.1
    calls_before = clock.calls
    assert st.jog_hold_check() == "hold"
    assert clock.calls - calls_before == 1
    assert st.view().last_hold == pytest.approx(1.1)


def c_jog_hold_admit_fresh() -> None:
    st = _new()
    assert st.jog_hold_admit() == (None, None)
    assert st.view().jog_starting is True


def c_jog_started_resets_latch() -> None:
    clock = _Clock(2.0)
    st = _new(clock)
    st.stop_written(1, None)
    assert st.view().latch_level == 1
    assert st.jog_started(_run(7)) is False
    v = st.view()
    assert v.jog.seq == 7
    assert v.jog.active is True
    assert v.last_hold == pytest.approx(2.0)
    assert _latch(v) == _CLEAN_LATCH


def c_take_next_job() -> None:
    st = _new()
    job = ("job", "j")
    st.enqueue_job(job)
    assert st.take_next_action() == (None, job)
    v = st.view()
    assert v.job_active is True
    assert v.job_queue == ()
    assert _latch(v) == _CLEAN_LATCH


def c_take_next_return_first() -> None:
    st = _new()
    job, ret = ("job", "j"), ("return", "r")
    st.enqueue_job(job)
    st.enqueue_return(ret)
    assert st.take_next_action() == (ret, None)
    v = st.view()
    assert v.job_active is False
    assert v.return_queue == ()
    assert v.job_queue == (job,)


def c_take_next_silent_during_program() -> None:
    st = _new()
    _program(st)
    job = ("job", "j")
    st.enqueue_job(job)
    before = st.view()
    assert before.job_queue == (job,)
    assert st.take_next_action() == (None, None)
    assert st.view() == before


def c_begin_sync_fresh() -> None:
    st = _new()
    assert st.begin_sync() is True
    assert st.view().syncing is True


def c_begin_sync_job_active() -> None:
    st = _new()
    _job(st)
    before = st.view()
    assert st.begin_sync() is False
    assert st.view() == before


def c_begin_sync_shutdown() -> None:
    st = _new()
    st.request_stop_begin()
    before = st.view()
    assert before.shutdown is True
    assert st.begin_sync() is False
    assert st.view() == before


def c_request_stop_begin() -> None:
    st = _new()
    st.stop_written(1, None)
    assert st.view().latch_level == 1
    assert st.request_stop_begin() is None
    v = st.view()
    assert v.shutdown is True
    assert _latch(v) == _CLEAN_LATCH
    # повторный вызов: сброса защёлки нет
    assert st.next_stop_attempt(_far_deadline(), _Counter(1.0)) == 1
    assert st.view().latch_attempts == 1
    assert st.request_stop_begin() is None
    v = st.view()
    assert v.latch_attempts == 1
    assert v.shutdown is True


def c_process_stop_plan_fresh() -> None:
    st = _new()
    assert st.process_stop_plan(lambda: True) == (1, None, False)
    v = st.view()
    assert v.stopping is True
    assert v.stop_level == 2


def c_process_stop_plan_program() -> None:
    st = _new()
    _program(st)
    connected = _Counter(True)
    assert st.process_stop_plan(connected) == (2, None, False)
    assert connected.calls == 0
    v = st.view()
    assert v.stopping is True
    assert v.stop_level == 2


def c_process_stop_plan_latch_held() -> None:
    st = _new()
    assert st.next_stop_attempt(_far_deadline(), _Counter(1.0)) == 1
    v = st.view()
    assert (v.latch_attempts, v.latch_failed) == (1, False)
    assert st.process_stop_plan(lambda: True) == (0, None, False)
    assert st.view().stopping is True


def c_next_stop_attempt_first() -> None:
    st = _new()
    budget = _Counter(1.0)
    assert st.next_stop_attempt(_far_deadline(), budget) == 1
    assert budget.calls == 0
    assert st.view().latch_attempts == 1


def c_next_stop_attempt_second() -> None:
    st = _new()
    assert st.next_stop_attempt(_far_deadline(), _Counter(1.0)) == 1
    budget = _Counter(1.0)
    assert st.next_stop_attempt(time.monotonic() + 10, budget) == 2
    assert budget.calls == 1
    assert st.view().latch_attempts == 2


def c_next_stop_attempt_no_time() -> None:
    st = _new()
    assert st.next_stop_attempt(_far_deadline(), _Counter(1.0)) == 1
    assert st.next_stop_attempt(time.monotonic() + 0.5, _Counter(1.0)) is None
    assert st.view().latch_attempts == 1


def c_next_stop_attempt_capped() -> None:
    st = _new()
    assert st.next_stop_attempt(_far_deadline(), _Counter(1.0)) == 1
    assert st.next_stop_attempt(_far_deadline(), _Counter(1.0)) == 2
    assert st.next_stop_attempt(_far_deadline(), _Counter(1.0)) is None
    assert st.view().latch_attempts == 2


def c_stop_written() -> None:
    st = _new()
    st.stop_written(2, None)
    run = _run(7)
    assert st.stop_written(0x0101, run) is None
    v = st.view()
    assert v.latch_level == 2
    assert v.latch_failed is False
    assert v.latch_value == 257
    assert run.stop_sent is True


def c_stop_write_failed() -> None:
    st = _new()
    assert st.stop_write_failed() is None
    assert st.view().latch_failed is True


def c_connect_reset() -> None:
    st = _new()
    text = "стоп не подтверждён роботом"
    st.mark_unconfirmed(text)
    st.process_stop_plan(lambda: True)
    assert st.view().stopping is True
    assert st.connect_reset() is None
    v = st.view()
    assert v.stopping is False
    assert v.stop_level == 0
    assert _latch(v) == _CLEAN_LATCH
    assert v.stop_unconfirmed is False
    assert v.stop_unconfirmed_text == text


def c_lease_check_expires() -> None:
    clock = _Clock(0.0)
    st = _new(clock)
    run = _run(7)
    st.jog_started(run)
    ev = threading.Event()
    clock.t = 0.1
    assert st.lease_check(run, ev) == ("lease", None, None)
    clock.t = 0.3
    assert st.lease_check(run, ev) == ("stop", "окно удержания истекло", False)
    assert st.view().jog.stop_requested is True


def c_lease_check_closing() -> None:
    clock = _Clock(0.0)
    st = _new(clock)
    run = _run(7)
    st.jog_started(run)
    ev = threading.Event()
    ev.set()
    calls_before = clock.calls
    assert st.lease_check(run, ev) == ("stop", "область закрывается", False)
    assert clock.calls == calls_before
    assert st.view().jog.stop_requested is True


_CONTRACTS = [
    c_fresh_view,
    c_admit_launch_fresh,
    c_admit_launch_stopping,
    c_admit_launch_program_busy,
    c_admit_launch_syncing,
    c_admit_launch_no_link,
    c_jog_hold_check_fresh,
    c_jog_hold_check_hold,
    c_jog_hold_admit_fresh,
    c_jog_started_resets_latch,
    c_take_next_job,
    c_take_next_return_first,
    c_take_next_silent_during_program,
    c_begin_sync_fresh,
    c_begin_sync_job_active,
    c_begin_sync_shutdown,
    c_request_stop_begin,
    c_process_stop_plan_fresh,
    c_process_stop_plan_program,
    c_process_stop_plan_latch_held,
    c_next_stop_attempt_first,
    c_next_stop_attempt_second,
    c_next_stop_attempt_no_time,
    c_next_stop_attempt_capped,
    c_stop_written,
    c_stop_write_failed,
    c_connect_reset,
    c_lease_check_expires,
    c_lease_check_closing,
]


@pytest.mark.parametrize("case", _CONTRACTS, ids=lambda fn: fn.__name__[2:])
def test_transition_contracts(case: Callable[[], None]) -> None:
    case()


# --------------------------------------------------------------------------------------------------
# REDS: снимок view() (Q9)
# --------------------------------------------------------------------------------------------------

_VIEW_FIELDS = {
    "program_active",
    "has_prog_handle",
    "job_active",
    "jog",
    "jog_starting",
    "jog_stopping",
    "last_hold",
    "syncing",
    "stopping",
    "shutdown",
    "stop_level",
    "latch_level",
    "latch_failed",
    "latch_value",
    "latch_attempts",
    "echo_checked",
    "stop_unconfirmed",
    "stop_unconfirmed_text",
    "own_stops",
    "job_queue",
    "return_queue",
    "returns_done",
    "returns_failed",
}
_JOGVIEW_FIELDS = {"seq", "active", "released", "stop_requested", "stop_sent", "has_handle"}


def test_view_is_frozen_snapshot() -> None:
    api = _api()
    st = _new()
    snap = st.view()
    assert isinstance(snap, api.RobotStateView)
    assert {f.name for f in dataclasses.fields(snap)} == _VIEW_FIELDS
    assert len(dataclasses.fields(snap)) == 23
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.shutdown = True  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.program_active = True  # type: ignore[misc]
    # переход после снятия не меняет снятый снимок
    _program(st)
    st.enqueue_return(("return", "r"))
    assert snap.program_active is False
    assert snap.return_queue == ()
    fresh = st.view()
    assert fresh.program_active is True
    assert fresh.return_queue == (("return", "r"),)
    assert isinstance(fresh.return_queue, tuple)
    assert isinstance(fresh.own_stops, tuple)
    assert isinstance(fresh.job_queue, tuple)


def test_view_jog_is_frozen_jogview() -> None:
    api = _api()
    st = _new()
    st.jog_started(_run(7))
    jog = st.view().jog
    assert isinstance(jog, api.JogView)
    assert {f.name for f in dataclasses.fields(jog)} == _JOGVIEW_FIELDS
    assert (jog.seq, jog.active, jog.released, jog.stop_requested, jog.stop_sent, jog.has_handle) == (
        7,
        True,
        False,
        False,
        False,
        False,
    )


# --------------------------------------------------------------------------------------------------
# REDS: инварианты I1–I8
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("owner", sorted(_OWNERS))
def test_motion_owner_is_exclusive(owner: str) -> None:
    """I3: владелец движения один — программа, задание или jog; второй не допускается ни одним входом."""
    st = _new()
    _OWNERS[owner](st)
    assert _owners_count(st.view()) == 1
    # запуск программы
    assert st.admit_launch(lambda: True)["status"] == "error"
    # взятие действия тиком: очередь не пуста, но действия нет
    st.enqueue_job(("job", "second"))
    assert st.take_next_action() == (None, None)
    # синхронизация не начинается
    assert st.begin_sync() is False
    # чужой jog: только если владелец не сам jog
    if not owner.startswith("jog"):
        assert st.jog_hold_admit()[0]["status"] == "error"
    v = st.view()
    assert _owners_count(v) == 1
    assert v.syncing is False


# (имя строки, цепочка построения, вход, ожидание). Порядок отказов — оракул, строки 9–17.
_ORDER_ROWS: list[tuple[str, list[Callable[[Any], Any]], str, Any]] = []


def _add(name: str, chain: list[Callable[[Any], Any]], entry: str, expected: Any) -> None:
    _ORDER_ROWS.append((f"{entry}:{name}", chain, entry, expected))


# _launch: останов -> программа -> задание -> jog -> синхронизация -> нет связи
_STOP_FIRST = [
    ("stop+program", [_program, _stopped]),
    ("stop+job", [_job, _stopped]),
    ("stop+jog", [lambda s: _jog_held(s), _stopped]),
    ("stop+sync", [_sync, _stopped]),
]
for _n, _chain in _STOP_FIRST:
    _add(_n, _chain, "launch", _err(T_STOP))
    _add(_n, _chain, "jog_hold_admit", _err(T_STOP))
    _add(_n, _chain, "jog_hold_check", _err(T_STOP))
    _add(_n, _chain, "motion_sync", _err(T_STOP))
    _add(_n, _chain, "motion_nosync", _err(T_STOP))
for _n, _chain, _text in [
    ("program", [_program], T_PROGRAM),
    ("job", [_job], T_JOB),
    ("jog", [lambda s: _jog_held(s)], T_JOG),
]:
    _add(_n, _chain, "launch", _err(_text))
    _add(_n, _chain, "motion_sync", _err(_text))
    _add(_n, _chain, "motion_nosync", _err(_text))
for _n, _chain, _text in [("program", [_program], T_PROGRAM), ("job", [_job], T_JOB)]:
    _add(_n, _chain, "jog_hold_admit", _err(_text))
    _add(_n, _chain, "jog_hold_check", _err(_text))
# jog_hold: свой jog держится — «hold» раньше синхронизации и нет связи
_add("own_jog", [lambda s: _jog_held(s)], "jog_hold_admit", "hold")
_add("own_jog", [lambda s: _jog_held(s)], "jog_hold_check", "hold")
# синхронизация
_add("sync", [_sync], "launch", _err(T_SYNC))
_add("sync", [_sync], "jog_hold_admit", _err(T_SYNC))
_add("sync", [_sync], "jog_hold_check", _err(T_SYNC))
_add("sync", [_sync], "motion_sync", _err(T_SYNC))
_add("sync", [_sync], "motion_nosync", None)  # servo / do_set: синхронизация НЕ отказ
# param gate: останов -> синхронизация; движение не отказ
_add("stop", [_stopped], "param", T_STOP)
_add("stop+sync", [_sync, _stopped], "param", T_STOP)
_add("sync", [_sync], "param", T_SYNC)
_add("program", [_program], "param", None)
_add("job", [_job], "param", None)
_add("fresh", [], "param", None)

_ORDER_CALLS: dict[str, Callable[[Any], Any]] = {
    "launch": lambda st: st.admit_launch(lambda: True),
    "jog_hold_admit": lambda st: st.jog_hold_admit()[0],
    "jog_hold_check": lambda st: st.jog_hold_check(),
    "motion_sync": lambda st: st.motion_refusal(True),
    "motion_nosync": lambda st: st.motion_refusal(False),
    "param": lambda st: st.param_refusal(),
}


@pytest.mark.parametrize(
    ("chain", "entry", "expected"),
    [pytest.param(chain, entry, expected, id=name) for name, chain, entry, expected in _ORDER_ROWS],
)
def test_refusal_order_per_entry(chain: list[Callable[[Any], Any]], entry: str, expected: Any) -> None:
    """I8: порядок отказов у входа фиксирован — отвечает первое условие; отказ не меняет состояние."""
    st = _new()
    for step in chain:
        step(st)
    before = st.view()
    assert _ORDER_CALLS[entry](st) == expected
    if expected != "hold":
        assert st.view() == before


@pytest.mark.parametrize(
    ("owner_text", "build"),
    [
        pytest.param(T_PROGRAM, _program, id="program"),
        pytest.param(T_JOB, _job, id="job"),
        pytest.param(T_JOG, lambda s: _jog_held(s), id="jog"),
        pytest.param(T_SYNC, _sync, id="sync"),
    ],
)
def test_refusal_order_launch_before_nolink(owner_text: str, build: Callable[[Any], Any]) -> None:
    """I8: ``_launch`` — «нет связи» последний: при занятости отвечает занятость; ``connected`` может не звать."""
    st = _new()
    build(st)
    assert st.admit_launch(lambda: False) == _err(owner_text)


_SILENT_SETUPS: dict[str, Callable[[Any], Any]] = {
    "stopped": _stopped,
    "sync": _sync,
    "program": _program,
    "job": _job,
    "jog_starting": _jog_starting,
    "jog_held": lambda s: _jog_held(s),
    "jog_stopping": _jog_stopping,
}


@pytest.mark.parametrize("setup", sorted(_SILENT_SETUPS))
def test_dispatch_and_sync_are_silent_under_blockers(setup: str) -> None:
    """I4/I8: тик молчит и синхронизация не начинается при останове, синхронизации, программе, jog, задании."""
    st = _new()
    _SILENT_SETUPS[setup](st)
    st.enqueue_job(("job", "queued"))
    st.enqueue_return(("return", "queued"))
    before = st.view()
    assert st.take_next_action() == (None, None)
    assert st.view() == before
    if setup != "sync":  # повторный begin_sync при идущей синхронизации оракул не определяет
        assert st.begin_sync() is False
    assert st.view() == before


def test_shutdown_is_terminal() -> None:
    """I1 + I2 (последовательно): выключение не снимается; после него вход -> «останавливается», connect -> False."""
    st = _new()
    assert st.is_shutdown() is False
    assert st.view().shutdown is False
    st.request_stop_begin()
    st.process_stop_plan(lambda: False)
    assert st.is_shutdown() is True
    # I2: запуск и jog_hold -> «останавливается»
    assert st.admit_launch(lambda: True) == _err(T_STOP)
    assert st.jog_hold_admit()[0] == _err(T_STOP)
    # connect отказывает выключением (ничего не сбрасывает)
    shutdown, job_active = st.connect_check()
    assert shutdown is True
    assert job_active is False
    assert st.begin_sync() is False
    # I1: ни один переход выключение не снимает
    steps: list[Callable[[], Any]] = [
        st.connect_reset,
        st.disconnect_begin,
        st.request_stop_begin,
        lambda: st.process_stop_plan(lambda: True),
        lambda: st.next_stop_attempt(_far_deadline(), _Counter(1.0)),
        lambda: st.stop_written(1, None),
        st.stop_write_failed,
        lambda: st.mark_unconfirmed("стоп не подтверждён роботом"),
        lambda: st.enqueue_job(("job", "late")),
        st.take_next_action,
    ]
    for step in steps:
        step()
        assert st.is_shutdown() is True
        assert st.view().shutdown is True
        assert st.begin_sync() is False


def test_sync_only_without_motion_and_stop() -> None:
    """I4: синхронизация начинается только без владельца движения и без останова; закончилась — можно снова."""
    st = _new()
    assert st.begin_sync() is True
    assert st.view().syncing is True
    st.end_sync()
    assert st.view().syncing is False
    assert st.begin_sync() is True
    st.end_sync()
    # при владельце движения — отказ
    for name, build in _OWNERS.items():
        other = _new()
        build(other)
        assert other.begin_sync() is False, name
        assert other.view().syncing is False, name
    # при останове — отказ
    stopped = _new()
    _stopped(stopped)
    assert stopped.begin_sync() is False
    # пока идёт синхронизация, владелец движения не появляется
    syncing = _new()
    assert syncing.begin_sync() is True
    assert syncing.admit_launch(lambda: True) == _err(T_SYNC)
    assert syncing.jog_hold_admit()[0] == _err(T_SYNC)
    syncing.enqueue_job(("job", "x"))
    assert syncing.take_next_action() == (None, None)
    v = syncing.view()
    assert (v.program_active, v.job_active, v.jog, v.jog_starting) == (False, False, None, False)


# Точки сброса поколения защёлки (оракул, I5 и таблица): (имя, действие, сбрасывает ли)
def _launch(st: Any) -> Any:
    return st.admit_launch(lambda: True)


def _take_job(st: Any) -> Any:
    st.enqueue_job(("job", "j"))
    return st.take_next_action()


def _no_setup(_st: Any) -> None:
    return None


def _in_connect(st: Any) -> None:
    """``connect`` идёт: ``connect_begin`` -> ``("go", False)`` (сам сбрасывает защёлку — до ``_dirty_latch``)."""
    assert st.connect_begin() == ("go", False)


def _connect_begin_is(kind: str) -> Callable[[Any], Any]:
    """Действие ``connect_begin`` с проверкой ветки ответа: строка доказывает, что setup привёл именно в неё."""

    def action(st: Any) -> Any:
        got = st.connect_begin()
        assert got[0] == kind
        return got

    return action


# Строка: (id, публичный метод ``RobotState`` — переход, setup ДО грязной защёлки, действие, сбрасывает ли)
_LATCH_ROWS: list[tuple[str, str, Callable[[Any], Any], Callable[[Any], Any], bool]] = [
    ("admit_launch", "admit_launch", _no_setup, _launch, True),
    ("jog_started", "jog_started", _no_setup, lambda st: st.jog_started(_run(7)), True),
    ("take_job", "take_next_action", _no_setup, _take_job, True),
    ("connect_reset", "connect_reset", _no_setup, lambda st: st.connect_reset(), True),
    ("request_stop_begin_first", "request_stop_begin", _no_setup, lambda st: st.request_stop_begin(), True),
    ("disconnect_begin_not_shutdown", "disconnect_begin", _no_setup, lambda st: st.disconnect_begin(), True),
    # T5.3g: вход connect — сброс только в ветке "go" (как connect_reset)
    ("connect_begin_go", "connect_begin", _no_setup, _connect_begin_is("go"), True),
    # не точки сброса
    ("jog_hold_admit", "jog_hold_admit", _no_setup, lambda st: st.jog_hold_admit(), False),
    ("jog_hold_check", "jog_hold_check", _no_setup, lambda st: st.jog_hold_check(), False),
    ("enqueue_job", "enqueue_job", _no_setup, lambda st: st.enqueue_job(("job", "j")), False),
    ("enqueue_return", "enqueue_return", _no_setup, lambda st: st.enqueue_return(("return", "r")), False),
    ("begin_sync", "begin_sync", _no_setup, lambda st: st.begin_sync(), False),
    ("admit_launch_refused_nolink", "admit_launch", _no_setup, lambda st: st.admit_launch(lambda: False), False),
    (
        "disconnect_soft_plan",
        "disconnect_soft_plan",
        _no_setup,
        lambda st: st.disconnect_soft_plan(lambda: True, lambda: True),
        False,
    ),
    ("disconnect_owns_close", "disconnect_owns_close", _no_setup, lambda st: st.disconnect_owns_close(), False),
    ("take_next_action_nothing", "take_next_action", _no_setup, lambda st: st.take_next_action(), False),
    ("view", "view", _no_setup, lambda st: st.view(), False),
    # C-29: «Отключить» и его счётчик защёлку не трогают
    ("disconnect_request", "disconnect_request", _no_setup, lambda st: st.disconnect_request(lambda: True), False),
    ("disconnect_end", "disconnect_end", _no_setup, lambda st: st.disconnect_end(), False),
    ("disconnect_pending", "disconnect_pending", _no_setup, lambda st: st.disconnect_pending(), False),
    ("disconnect_refusal", "disconnect_refusal", _no_setup, lambda st: st.disconnect_refusal(), False),
    # T5.3g: ветки connect_begin без сброса и вехи connect
    (
        "connect_begin_shutdown",
        "connect_begin",
        lambda st: st.request_stop_begin(),
        _connect_begin_is("shutdown"),
        False,
    ),
    (
        "connect_begin_cancelled",
        "connect_begin",
        lambda st: st.disconnect_request(lambda: True),
        _connect_begin_is("cancelled"),
        False,
    ),
    ("connect_begin_busy", "connect_begin", _job, _connect_begin_is("busy"), False),
    ("connect_link_up", "connect_link_up", _in_connect, lambda st: st.connect_link_up(), False),
    ("connect_restore", "connect_restore", _in_connect, lambda st: st.connect_restore(True), False),
    ("connect_finish", "connect_finish", _in_connect, lambda st: st.connect_finish(), False),
    ("connect_end", "connect_end", _in_connect, lambda st: st.connect_end(), False),
    ("set_ready", "set_ready", _no_setup, lambda st: st.set_ready(True), False),
    ("connect_check", "connect_check", _no_setup, lambda st: st.connect_check(), False),
    ("is_shutdown", "is_shutdown", _no_setup, lambda st: st.is_shutdown(), False),
]

# Литерал (SPI.md D8): публичные методы ``RobotState``, сбрасывающие поколение защёлки хоть в одной ветке
_RESET_TRANSITIONS = frozenset(
    {
        "admit_launch",
        "connect_begin",
        "connect_reset",
        "disconnect_begin",
        "jog_started",
        "request_stop_begin",
        "take_next_action",
    }
)

# Публичные методы ``RobotState`` (не свойства) вне таблицы: защёлку не сбрасывают, строки не нужно
# (выписано из AST ``state.py`` базы 2667f8a5d: 63 публичных метода - 26 переходов строк = 37)
_LATCH_EXEMPT = frozenset(
    {
        "activity_alive",
        "disconnect_stop_plan",
        "echo_check_plan",
        "end_sync",
        "is_own_stop",
        "is_stopping",
        "job_finished",
        "job_queue_len",
        "jog_aborted_by_stop",
        "jog_release_begin",
        "jog_release_done",
        "jog_spawn_failed",
        "jog_start_done",
        "latch_covers",
        "launch_failed",
        "lease_check",
        "lease_exit",
        "mark_unconfirmed",
        "motion_refusal",
        "next_stop_attempt",
        "note_own_stop",
        "param_refusal",
        "process_stop_plan",
        "program_finished",
        "program_running",
        "program_started",
        "requeue_job",
        "requeue_return",
        "return_failed",
        "return_queue_len",
        "stop_resend_level",
        "stop_unconfirmed",
        "stop_unconfirmed_text",
        "stop_write_failed",
        "stop_written",
        "sync_cancelled",
        "threads_to_close",
    }
)


@pytest.mark.parametrize(
    ("setup", "action", "resets"),
    [pytest.param(setup, action, resets, id=name) for name, _tr, setup, action, resets in _LATCH_ROWS],
)
def test_latch_generation_reset_points(setup: Callable[[Any], Any], action: Callable[[Any], Any], resets: bool) -> None:
    """I5: поколение защёлки сбрасывается ровно в точках таблицы; прочие переходы его не трогают."""
    st = _new()
    setup(st)
    before = _dirty_latch(st)
    action(st)
    after = _latch(st.view())
    if resets:
        assert after == _CLEAN_LATCH
    else:
        assert after == before


# --- Полнота оракула защёлки (SPI.md D8): AST ``state.py`` без импорта пакета ---

_STATE_PY = Path(__file__).resolve().parents[1] / "drivers" / "robot_driver_v2" / "state.py"
_RESET_HELPER = "_latch_reset_locked"


def _state_methods() -> dict[str, ast.FunctionDef]:
    tree = ast.parse(_STATE_PY.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "RobotState")
    return {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}


def _is_property_def(node: ast.FunctionDef) -> bool:
    return any(isinstance(d, ast.Name) and d.id == "property" for d in node.decorator_list)


def _public_state_methods() -> frozenset[str]:
    """Публичные методы ``RobotState`` без свойств — тот же отбор, что ``_transitions`` сторожа."""
    methods = _state_methods()
    return frozenset(n for n, node in methods.items() if not n.startswith("_") and not _is_property_def(node))


def _self_calls(node: ast.FunctionDef, names: frozenset[str]) -> set[str]:
    """Имена методов класса, вызванных как ``self.<имя>(...)`` в теле ``node``."""
    out: set[str] = set()
    for sub in ast.walk(node):
        if not (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)):
            continue
        target = sub.func
        if isinstance(target.value, ast.Name) and target.value.id == "self" and target.attr in names:
            out.add(target.attr)
    return out


def _methods_reaching_reset() -> frozenset[str]:
    """Публичные методы, из которых по цепочке ``self.<метод>()`` достижим ``_latch_reset_locked``."""
    methods = _state_methods()
    names = frozenset(methods)
    assert _RESET_HELPER in names  # достижимость: помощник сброса существует под этим именем
    calls = {name: _self_calls(node, names) for name, node in methods.items()}
    reaching = {_RESET_HELPER}
    changed = True
    while changed:
        changed = False
        for name, callees in calls.items():
            if name not in reaching and callees & reaching:
                reaching.add(name)
                changed = True
    return frozenset(n for n in reaching if not n.startswith("_"))


def test_latch_reset_transitions_match_state_ast() -> None:
    """(1) Публичные методы, достигающие сброса защёлки через помощники, — ровно литерал."""
    assert _methods_reaching_reset() == _RESET_TRANSITIONS


def test_latch_rows_cover_every_reset_transition() -> None:
    """(2) Переходы строк со сбросом — ровно литерал: каждая точка сброса имеет строку оракула."""
    assert {tr for _id, tr, _setup, _action, resets in _LATCH_ROWS if resets} == _RESET_TRANSITIONS


def test_latch_rows_or_exempt_cover_every_public_method() -> None:
    """(3) Каждый публичный метод ``RobotState`` — переход строки или в ``_LATCH_EXEMPT``; исключения не сбрасывают."""
    public = _public_state_methods()
    rows = {tr for _id, tr, _setup, _action, _resets in _LATCH_ROWS}
    assert rows <= public, f"переход строки не публичный метод: {sorted(rows - public)}"
    assert public - rows == _LATCH_EXEMPT
    assert not (rows & _LATCH_EXEMPT)
    assert not (_LATCH_EXEMPT & _RESET_TRANSITIONS)


def test_latch_not_reset_by_disconnect_after_shutdown() -> None:
    """I5: ``disconnect_begin`` после выключения защёлку не сбрасывает."""
    st = _new()
    st.request_stop_begin()
    before = _dirty_latch(st)
    assert st.disconnect_begin() is True
    assert _latch(st.view()) == before


def test_disconnect_begin_marks_stop() -> None:
    """Оракул, ``disconnect`` = ``disconnect_begin`` + ``disconnect_stop_plan``: останов и уровень не ниже SOFT (1).

    Поправка лида 2026-10-20 (строка 19 оракула описывала весь ``disconnect`` одним переходом; останов ставит
    ``disconnect_stop_plan`` — секция ``_request_stop`` базы :880, ``disconnect_begin`` только сбрасывает защёлку).
    """
    st = _new()
    assert st.disconnect_begin() is False
    v = st.view()
    assert v.stopping is False
    assert v.stop_level == 0
    st.disconnect_stop_plan(1)
    v = st.view()
    assert v.stopping is True
    assert v.stop_level == 1


# --- T5.3h: SOFT при обычном «Отключить» посреди connect (контракт S1-S10, литералы брифа) ---


def _link_up_state() -> Any:
    """Робот был готов, ``connect`` идёт, связь поднята (``connect_begin`` -> ``("go", True)``)."""
    st = _new()
    st.set_ready(True)
    assert st.connect_begin() == ("go", True)
    return st


def _lu() -> bool:
    return True


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        pytest.param("s1_connected_robot", True, id="S1"),
        pytest.param("s2_no_snapshot", False, id="S2"),
        pytest.param("s3_snapshot_link_up", True, id="S3"),
        pytest.param("s4_snapshot_link_down", False, id="S4"),
        pytest.param("s5_latch_covers", False, id="S5"),
    ],
)
def test_disconnect_soft_plan_contract(name: str, expected: bool) -> None:
    """S1-S5: ``disconnect_soft_plan`` — подключён или (снимок связи и транспорт жив), и защёлка не покрывает."""
    if name == "s1_connected_robot":
        st = _new()
        got = st.disconnect_soft_plan(lambda: True, lambda: False)
    elif name == "s2_no_snapshot":
        st = _new()
        got = st.disconnect_soft_plan(lambda: False, lambda: True)
    elif name == "s3_snapshot_link_up":
        st = _link_up_state()
        st.disconnect_stop_plan(1, link_up=_lu)
        got = st.disconnect_soft_plan(lambda: False, lambda: True)
    elif name == "s4_snapshot_link_down":
        st = _link_up_state()
        st.disconnect_stop_plan(1, link_up=_lu)
        got = st.disconnect_soft_plan(lambda: False, lambda: False)
    else:
        st = _link_up_state()
        st.disconnect_stop_plan(1, link_up=_lu)
        st.stop_written(1, None)
        got = st.disconnect_soft_plan(lambda: False, lambda: True)
    assert got is expected


def test_s6_request_stop_snapshot_survives_disconnect_plan() -> None:
    """S6 (п. 1 р.1): снимок ``request_stop`` не переписывается стоп-секцией ``disconnect`` после выключения."""
    st = _link_up_state()
    st.request_stop_begin()
    st.connect_end()
    st.disconnect_stop_plan(1, link_up=_lu)
    assert st.process_stop_plan(lambda: False, link_up=lambda: True)[0] == 1


def test_s7_disconnect_snapshot_survives_request_stop() -> None:
    """S7 (п. 2 р.1): снимок стоп-секции ``disconnect`` монотонен — ``request_stop_begin`` его не обнуляет."""
    st = _link_up_state()
    st.disconnect_stop_plan(1, link_up=_lu)
    st.connect_end()
    st.request_stop_begin()
    assert st.process_stop_plan(lambda: False, link_up=lambda: True)[0] == 1


def test_s8_disconnect_owns_close() -> None:
    """S8: транспорт закрывает хвост обычного ``disconnect``, решившего «связь поднята»; не ``request_stop``."""
    st = _link_up_state()
    st.disconnect_stop_plan(1, link_up=_lu)
    assert st.disconnect_owns_close() is True
    st.request_stop_begin()
    assert st.disconnect_owns_close() is False
    bare = _new()
    bare.disconnect_stop_plan(1, link_up=_lu)
    assert bare.disconnect_owns_close() is False


def test_s9_snapshot_reset_by_connect_and_taken_before_stopping() -> None:
    """S9 (п. 2 р.2): ``connect_begin`` сбрасывает снимок; в стоп-секции он считается ДО ``_stopping = True``."""
    st = _link_up_state()
    st.disconnect_stop_plan(1, link_up=_lu)
    st.connect_end()
    assert st.connect_begin() == ("go", False)
    assert st.disconnect_owns_close() is False  # _stopping снят connect_begin: терм _stopping признака
    st.disconnect_stop_plan(1, link_up=_lu)
    assert st.disconnect_soft_plan(lambda: False, lambda: True) is False
    assert st.disconnect_owns_close() is False


def test_s10_snapshot_needs_live_link() -> None:
    """S10 (п. 1 р.2): связь упала до стоп-секции — снимок не пишется, закрывает тик, не хвост ``disconnect``."""
    st = _link_up_state()
    st.disconnect_stop_plan(1, link_up=lambda: False)
    assert st.disconnect_owns_close() is False


# --- C-29: «Отключить» прерывает connect (контракт R1-R10, литералы tasks/C-29.injections.md) ---

T_DISCONNECTING = "идёт отключение робота"


def _linked_connect() -> Any:
    """``connect`` идёт, связь поднята: ``connect_begin`` -> ``("go", False)`` + ``connect_link_up`` -> True."""
    st = _new()
    assert st.connect_begin() == ("go", False)
    assert st.connect_link_up() is True
    return st


def _dsoft_after_dsp(st: Any, link_up: bool = True) -> bool:
    st.connect_end()
    st.disconnect_stop_plan(1, link_up=lambda: True)
    return st.disconnect_soft_plan(lambda: False, lambda: link_up)


def test_r1_k_with_link_up_gives_soft() -> None:
    """R1: связь поднята, K, ``connect_finish`` отказывает; после выхода ``connect`` снимок даёт SOFT."""
    st = _linked_connect()
    st.disconnect_request(lambda: True)
    assert st.connect_finish() is False
    assert _dsoft_after_dsp(st) is True


def test_r2_k_before_link_up_no_soft() -> None:
    """R2: K до подъёма связи — ``connect_link_up`` отказывает, SOFT нет."""
    st = _new()
    assert st.connect_begin() == ("go", False)
    st.disconnect_request(lambda: True)
    assert st.connect_link_up() is False
    assert _dsoft_after_dsp(st) is False


def test_r3_k_without_connect_cancels_next_connect_until_end() -> None:
    """R3: K без ``connect`` — следующий ``connect_begin`` "cancelled"; после ``disconnect_end`` — "go"."""
    st = _new()
    st.disconnect_request(lambda: True)
    assert st.connect_begin()[0] == "cancelled"
    st.disconnect_end()
    assert st.connect_begin()[0] == "go"


def test_r4_k_with_dead_link_no_soft() -> None:
    """R4: транспорт мёртв к моменту K — снимок False, SOFT нет."""
    st = _linked_connect()
    st.disconnect_request(lambda: False)
    assert _dsoft_after_dsp(st) is False


def test_r5_k_after_shutdown_is_noop() -> None:
    """R5: после ``request_stop_begin`` K ничего не считает — ``connect_begin`` отвечает "shutdown"."""
    st = _new()
    st.request_stop_begin()
    st.disconnect_request(lambda: True)
    assert st.connect_begin()[0] == "shutdown"
    assert st.disconnect_pending() is False


def test_r6_k_with_ready_robot_owns_close() -> None:
    """R6: робот был готов (``("go", True)``), K — SOFT и закрытие за хвостом ``disconnect``."""
    st = _new()
    st.set_ready(True)
    assert st.connect_begin() == ("go", True)
    st.disconnect_request(lambda: True)
    assert _dsoft_after_dsp(st) is True
    assert st.disconnect_owns_close() is True


def test_r7_cancelled_before_busy() -> None:
    """R7: при задании тика и K ``connect_begin`` отвечает "cancelled", не "busy"."""
    st = _new()
    job = ("job", "owner")
    st.enqueue_job(job)
    assert st.take_next_action() == (None, job)
    st.disconnect_request(lambda: True)
    assert st.connect_begin()[0] == "cancelled"


def test_r8_counter_pairs_and_floor() -> None:
    """R8: два K — два ``disconnect_end``; лишний ``disconnect_end`` ниже нуля не уходит."""
    st = _new()
    st.disconnect_request(lambda: True)
    st.disconnect_request(lambda: True)
    st.disconnect_end()
    assert st.connect_begin()[0] == "cancelled"
    assert st.disconnect_pending() is True
    st.disconnect_end()
    assert st.disconnect_pending() is False
    st.disconnect_end()
    st.disconnect_request(lambda: True)
    st.disconnect_end()
    assert st.connect_begin()[0] == "go"


def test_r9_refusals_and_job_queue_cleared() -> None:
    """R9 (В4, В6): отказ jog и задания текстом, очередь не берётся, ``disconnect_end`` снимает задание."""
    refusal = {"status": "error", "message": T_DISCONNECTING}
    st = _new()
    st.disconnect_request(lambda: True)
    assert st.disconnect_refusal() == refusal
    assert st.jog_hold_check() == refusal
    assert st.jog_hold_admit() == (refusal, None)
    st.enqueue_job(("job", "j"))
    assert st.take_next_action() == (None, None)
    assert st.disconnect_end() == (1, 0)
    assert st.job_queue_len() == 0
    assert st.disconnect_refusal() is None
    bare = _new()
    bare.enqueue_job(("job", "j"))
    assert bare.disconnect_end() == (0, 0)
    assert bare.job_queue_len() == 1


def test_r10_launch_refused_and_return_queue_cleared() -> None:
    """R10 (В5, В6): запуск исполнителя отказывает, возврат не берётся, ``disconnect_end`` снимает возврат."""
    st = _new()
    st.disconnect_request(lambda: True)
    assert st.admit_launch(lambda: True) == {"status": "error", "message": T_DISCONNECTING}
    st.enqueue_return((1.0, 2.0, 0.0))
    assert st.take_next_action() == (None, None)
    assert st.disconnect_end() == (0, 1)
    assert st.return_queue_len() == 0
    assert st.admit_launch(lambda: True) is None


def test_process_stop_attempts_capped_at_two() -> None:
    """I6: не больше 2 попыток стопа процесса на поколение защёлки; новое поколение — снова с первой."""
    st = _new()
    results = [st.next_stop_attempt(_far_deadline(), _Counter(1.0)) for _ in range(5)]
    assert results == [1, 2, None, None, None]
    assert st.view().latch_attempts == 2
    st.connect_reset()
    assert st.view().latch_attempts == 0
    assert st.next_stop_attempt(_far_deadline(), _Counter(1.0)) == 1


def test_unconfirmed_cleared_only_by_connect() -> None:
    """I7: «стоп не подтверждён» снимает только ``connect``; текст причины не снимается."""
    st = _new()
    text = "стоп не подтверждён роботом"
    assert st.stop_unconfirmed() is False
    assert st.stop_unconfirmed_text() is None
    st.mark_unconfirmed(text)
    assert st.stop_unconfirmed() is True
    assert st.stop_unconfirmed_text() == text
    steps: list[Callable[[], Any]] = [
        lambda: st.begin_sync(),
        lambda: st.end_sync(),
        lambda: st.jog_hold_admit(),
        lambda: st.enqueue_job(("job", "j")),
        lambda: st.enqueue_return(("return", "r")),
        lambda: st.stop_written(1, None),
        lambda: st.stop_write_failed(),
        lambda: st.next_stop_attempt(_far_deadline(), _Counter(1.0)),
        lambda: st.process_stop_plan(lambda: True),
        lambda: st.disconnect_begin(),
        lambda: st.request_stop_begin(),
        lambda: st.view(),
    ]
    for step in steps:
        step()
        assert st.stop_unconfirmed() is True
        assert st.view().stop_unconfirmed is True
    st.connect_reset()
    assert st.stop_unconfirmed() is False
    assert st.view().stop_unconfirmed is False
    assert st.stop_unconfirmed_text() == text
    assert st.view().stop_unconfirmed_text == text


# --------------------------------------------------------------------------------------------------
# Драйвер с фейковым клиентом (копия образца ``_fake_driver``); характеризация через ``drv.call``
# --------------------------------------------------------------------------------------------------


def _free_tlm() -> list[int]:
    base = REG["TLM_PROTO_VER"]
    words = [0] * 32
    words[REG["TLM_SERVO"] - base] = 1
    words[REG["TLM_CFG_EPOCH"] - base] = 1
    return words


class _FakeTransport:
    def __init__(self) -> None:
        self.is_connected = True
        self.closed = 0
        self.tlm = _free_tlm()

    def connect(self) -> bool:
        self.is_connected = True
        return True

    def disconnect(self) -> None:
        self.closed += 1
        self.is_connected = False

    def read_registers(self, _address: int, _count: int) -> list[int]:
        return list(self.tlm)


class _FakeClient:
    """Клиент v2 на границе драйвера; неизвестные методы пишутся в ``calls`` и отвечают ``None``."""

    heartbeat_period_s = None
    jog_lease_period_s = None

    def __init__(self) -> None:
        self.cvt: list[tuple] = []
        self.stops: list[int] = []
        self.stop_calls = 0
        self.jog_conts: list[tuple] = []
        self.calls: list[str] = []
        self.probes = 0
        self.heartbeats = 0
        self.wait: Callable[[Callable[[Any], None] | None], None] = lambda _poll: None
        self.run: Callable[[], None] = lambda: None
        self.stopped = threading.Event()

    def __getattr__(self, name: str) -> Callable[..., Any]:
        if name.startswith("__"):
            raise AttributeError(name)

        def record(*_args: Any, **_kwargs: Any) -> None:
            self.calls.append(name)

        return record

    def probe(self) -> None:
        self.probes += 1

    def sync_params(self, _values: Any, _epoch: int, *, cancelled: Any = None) -> None:
        pass

    def kick_heartbeat(self) -> None:
        self.heartbeats += 1

    def poll_errors(self) -> list:
        return []

    def jog_cont(self, *args: Any) -> Any:
        self.jog_conts.append(args)
        return type("Res", (), {"seq": len(self.jog_conts)})()

    def cvt_job(self, *args: Any) -> Any:
        self.cvt.append(args)
        return type("Res", (), {"seq": len(self.cvt)})()

    def wait_done(self, _seq: int, *, on_poll: Callable[[Any], None] | None = None) -> None:
        self.wait(on_poll)

    def stop(self, level: int) -> None:
        self.stop_calls += 1
        self.stops.append(level)
        self.stopped.set()

    def issue_stop(self, level: int) -> int:
        self.stop(level)
        return len(self.stops) * 4 + level

    def await_stop_echo(self, _value: int, _level: int, *, deadline: float) -> None:
        pass

    def run_chunks(self, _scenario: Any, *, params: Any, on_progress: Any) -> None:
        self.run()


class _FailingStopClient(_FakeClient):
    """Каждая запись стопа сбоит: защёлка «не записана», следующий ``request_stop`` пробует снова."""

    def issue_stop(self, level: int) -> int:
        self.stop_calls += 1
        self.stops.append(level)
        from Services.robot_comm.errors import RobotTimeout

        raise RobotTimeout("res")


def _bounded(fn: Callable[[], Any], deadline_s: float = 15.0) -> Any:
    """Вызов в daemon-потоке с дедлайном join: зависший драйвер даёт красный тест, а не зависание."""
    box: dict[str, Any] = {}

    def runner() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — исключение возвращается в поток теста
            box["error"] = exc

    thread = threading.Thread(target=runner, name="state-acceptance-call", daemon=True)
    thread.start()
    thread.join(deadline_s)
    if thread.is_alive():
        raise AssertionError(f"вызов завис дольше {deadline_s} с")
    if "error" in box:
        raise box["error"]
    return box.get("result")


@pytest.fixture
def make_driver() -> Iterator[Callable[..., tuple[Any, Any]]]:
    scope = open_scope("rv2stateacc", budget_s=6.0)
    made: list[Any] = []

    def make(client_cls: type = _FakeClient) -> tuple[Any, Any]:
        from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2

        entry = DeviceEntry(
            id="rv2",
            name="rv2",
            kind="robot",
            protocol="delta_v2",
            transport={"type": "tcp", "host": "127.0.0.1", "port": 1, "unit_id": ROBOT_UNIT_ID},
            params={},
        )
        transport = _FakeTransport()
        drv = RobotDriverV2(entry, None, transport=transport, publish=lambda _p, _v: None, spawn=scope.spawn)
        client = client_cls()
        drv._client = client  # шов по образцу _fake_driver: клиент v2 без sim
        assert _bounded(drv.connect) is True
        transport.closed = 0
        drv.desired_connected = True
        made.append((drv, client))
        return drv, client

    try:
        yield make
    finally:
        for drv, client in made:
            client.stopped.set()
            try:
                _bounded(drv.disconnect, 15.0)
            except Exception:  # noqa: BLE001 — уборка не подменяет исключение теста
                pass
        report = scope.close()
        assert list(report.survivors) == [], f"выжившие потоки области теста: {list(report.survivors)}"


def _program_pack() -> tuple[Any, dict]:
    points = {
        "a": Point(name="a", x=400, y=100, z=-60, rz=0, hand=1),
        "b": Point(name="b", x=300, y=-210, z=-40, rz=-100, hand=1),
    }
    program = Program(name="race", steps=tuple(Move(point="a" if i % 2 == 0 else "b", kind="JOINT") for i in range(4)))
    return program, points


def _start_program(drv: Any) -> dict:
    program, points = _program_pack()
    return _bounded(lambda: drv.start_program(program, points, None, name="race"))


_CALL_ENTRIES = [
    ("jog_hold", _JOG_ARGS),
    ("jog_step", {"dx": 10, "dy": 0, "spd": 50}),
    ("servo", {"on": True}),
    ("do_set", {"ch": 3, "on": True}),
    ("param_apply", {}),
]


def _call(drv: Any, op: str, args: dict) -> dict:
    return _bounded(lambda: drv.call(op, dict(args)))


@pytest.mark.parametrize(("op", "args"), _CALL_ENTRIES, ids=[op for op, _ in _CALL_ENTRIES])
def test_char_every_entry_refuses_after_request_stop(
    make_driver: Callable[..., tuple[Any, Any]], op: str, args: dict
) -> None:  # characterization
    """I1/I2/I8 через ``call``: после вернувшегося ``request_stop`` каждый вход отвечает «останавливается»."""
    drv, _client = make_driver()
    _bounded(drv.request_stop)
    assert _call(drv, op, args) == _err(T_STOP)


def test_char_program_start_refused_after_request_stop(
    make_driver: Callable[..., tuple[Any, Any]],
) -> None:  # characterization
    drv, _client = make_driver()
    _bounded(drv.request_stop)
    assert _start_program(drv) == _err(T_STOP)


def test_char_shutdown_is_terminal_via_connect(make_driver: Callable[..., tuple[Any, Any]]) -> None:  # characterization
    """I1/I2 через драйвер: после ``request_stop`` ``connect`` -> False и после ``disconnect`` тоже."""
    drv, _client = make_driver()
    _bounded(drv.request_stop)
    assert _bounded(drv.connect) is False
    _bounded(drv.disconnect)
    assert _bounded(drv.connect) is False
    _bounded(drv.request_stop)  # повторный вызов безопасен
    assert _bounded(drv.connect) is False
    assert _call(drv, "jog_hold", _JOG_ARGS) == _err(T_STOP)


@pytest.mark.parametrize(
    ("op", "args"),
    [entry for entry in _CALL_ENTRIES if entry[0] in ("jog_hold", "jog_step", "servo", "do_set")],
    ids=["jog_hold", "jog_step", "servo", "do_set"],
)
def test_char_program_owns_motion(
    make_driver: Callable[..., tuple[Any, Any]], op: str, args: dict
) -> None:  # characterization
    """I3 через ``call``: пока идёт программа, движение и второй запуск отказывают «занят программой»."""
    drv, client = make_driver()
    gate = threading.Event()
    client.run = lambda: gate.wait(10.0)
    try:
        assert _start_program(drv)["status"] == "ok"
        assert _call(drv, op, args) == _err(T_PROGRAM)
        assert _start_program(drv) == _err(T_PROGRAM)
    finally:
        gate.set()


def test_char_stop_beats_program(make_driver: Callable[..., tuple[Any, Any]]) -> None:  # characterization
    """I8 через ``call``: останов раньше «занят программой»."""
    drv, client = make_driver()
    client.run = lambda: client.stopped.wait(10.0)
    assert _start_program(drv)["status"] == "ok"
    assert _call(drv, "jog_hold", _JOG_ARGS) == _err(T_PROGRAM)
    _bounded(drv.request_stop)
    assert _call(drv, "jog_hold", _JOG_ARGS) == _err(T_STOP)
    assert _start_program(drv) == _err(T_STOP)


def test_char_jog_owns_motion(make_driver: Callable[..., tuple[Any, Any]]) -> None:  # characterization
    """I3 через ``call``: держащийся jog — продление без второго ``JOG_CONT``; запуск и движение отказывают «jog»."""
    drv, client = make_driver()
    assert _call(drv, "jog_hold", _JOG_ARGS)["status"] == "ok"
    assert len(client.jog_conts) == 1
    assert _call(drv, "jog_hold", _JOG_ARGS)["status"] == "ok"
    assert len(client.jog_conts) == 1
    assert _start_program(drv) == _err(T_JOG)
    assert _call(drv, "jog_step", {"dx": 10, "dy": 0, "spd": 50}) == _err(T_JOG)
    assert _call(drv, "servo", {"on": True}) == _err(T_JOG)
    assert _call(drv, "do_set", {"ch": 3, "on": True}) == _err(T_JOG)


def test_char_process_stop_attempts_capped_at_two(
    make_driver: Callable[..., tuple[Any, Any]],
) -> None:  # characterization
    """I6 через драйвер: при непрерывном сбое записи стопа на поколение выходит ровно 2 попытки."""
    drv, client = make_driver(_FailingStopClient)
    for _ in range(4):
        _bounded(drv.request_stop)
    assert client.stop_calls == 2


# --------------------------------------------------------------------------------------------------
# REDS: accessor драйвера
# --------------------------------------------------------------------------------------------------


def test_driver_state_accessor_is_read_only(make_driver: Callable[..., tuple[Any, Any]]) -> None:
    """``RobotDriverV2.state`` — только чтение; состояние живого драйвера отражает вызванные переходы."""
    api = _api()
    drv, _client = make_driver()
    assert isinstance(drv.state, api.RobotState)
    assert drv.state.view().shutdown is False
    with pytest.raises(AttributeError):
        drv.state = _new()  # type: ignore[misc]
    _bounded(drv.request_stop)
    assert drv.state.view().shutdown is True
