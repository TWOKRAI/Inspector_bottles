"""Тесты автора T5.3e.1 (бриф 1a): переходы park в ``RobotState`` и ``ParkMachine`` с поддельными колбэками.

Purpose:
    Хазарды основной остановки без драйвера и sim: пометки release держащегося jog, окно ``_jog_starting``,
    сравнение по ``seq`` в ``park_end``, ``_parked`` при ``failed``, отказ ``param_set``, устаревшие шаги и
    финишеры автомата, замирание при выключении. Ожидаемые значения — литералы спеки.

Public API:
    Только тесты ``test_*``.

Stability: lite
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

from Services.robot_comm.programs import Point

_TEXT_PARKING = "идёт основная остановка робота"
_TEXT_STOPPING = "драйвер робота останавливается"
_TEXT_HOME_FAILED = "ход домой не выполнен"
_JOIN_S = 5.0
_HOME = {"x_mm": 300.0, "y_mm": 0.0, "z_mm": -50.0, "rz_deg": 0.0}
_AWAY = {"x_mm": 380.0, "y_mm": 0.0, "z_mm": -50.0, "rz_deg": 0.0}


def _api() -> SimpleNamespace:
    """Имена — внутри вызова: на базе без park падает тело теста, а не сбор."""
    from Services.device_hub.drivers import robot_driver_v2 as module
    from Services.device_hub.drivers.robot_driver_v2.park import ParkMachine

    return SimpleNamespace(RobotState=module.RobotState, JogRun=module._JogRun, ParkMachine=ParkMachine)


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _state(clock: _Clock | None = None) -> Any:
    return _api().RobotState(clock=clock or _Clock(), queue_maxlen=16)


class _Fakes:
    """Колбэки ``ParkMachine``: публикации, вызовы ``launch_home`` / ``servo_off``; поведение задаёт тест."""

    def __init__(self, st: Any) -> None:
        self.st = st
        self.pubs: list[dict] = []
        self.launches: list[int] = []
        self.servo_calls = 0
        self.errors = 0
        self.launch_fn = self.launch_ok
        self.servo_fn = lambda: True

    def launch_ok(self, seq: int) -> dict:
        refusal = self.st.admit_launch(lambda: True, kind="park", park_seq=seq)
        return refusal or {"status": "ok"}

    def launch(self, seq: int) -> dict:
        self.launches.append(seq)
        return self.launch_fn(seq)

    def servo(self) -> bool:
        self.servo_calls += 1
        return self.servo_fn()

    def machine(self, clock: _Clock | None = None) -> Any:
        return _api().ParkMachine(
            state=self.st,
            clock=clock or _Clock(),
            publish=self.pubs.append,
            home_point=lambda: Point(name="home", x=300.0, y=0.0, z=-50.0, rz=0.0, hand=1),
            launch_home=self.launch,
            servo_off=self.servo,
            heartbeat=lambda: None,
            record_err=self._err,
            log_id="rtest",
        )

    def _err(self) -> None:
        self.errors += 1


def _begin(st: Any) -> Any:
    b = st.park_begin()
    assert b.refusal is None, b.refusal
    return b


def _in_thread(fn: Any) -> threading.Thread:
    t = threading.Thread(target=fn, daemon=True)
    t.start()
    return t


# --------------------------------------------------------------------------------------------------
# RobotState
# --------------------------------------------------------------------------------------------------


def test_park_begin_marks_holding_jog_released() -> None:
    st = _state()
    decision, _prev = st.jog_hold_admit()
    assert decision is None
    run = _api().JogRun(seq=5)
    assert st.jog_started(run) is False
    st.jog_start_done()
    b = _begin(st)
    assert b.run is run
    assert st.lease_check(run, threading.Event()) == ("released", None, None)
    assert st.park_view().jog_busy is True  # jog_stopping до возврата стопа


def test_jog_started_during_parking_returns_stop() -> None:
    st = _state()
    decision, _prev = st.jog_hold_admit()  # JOG_CONT в полёте: держащегося jog нет
    assert decision is None
    b = _begin(st)
    assert b.run is None
    assert st.jog_started(_api().JogRun(seq=6)) is True


def test_park_end_stale_seq_is_noop() -> None:
    st = _state()
    assert _begin(st).seq == 1
    assert st.park_end(1, False) == (True, 0, 0)
    assert _begin(st).seq == 2
    assert st.park_end(1, True) == (False, 0, 0)
    v = st.park_view()
    assert v.parking is True
    assert v.parked is False


def test_failed_park_keeps_parked_unchanged() -> None:
    st = _state()
    _begin(st)
    assert st.park_end(1, True)[0] is True
    assert st.park_view().parked is True
    _begin(st)
    assert st.park_end(2, False)[0] is True
    assert st.park_view().parked is True  # failed не снимает запрет
    st.servo_on_done()
    _begin(st)
    assert st.park_end(3, False)[0] is True
    assert st.park_view().parked is False  # и не ставит его


def test_param_refused_while_parking() -> None:
    st = _state()
    _begin(st)
    assert st.param_refusal() == _TEXT_PARKING
    assert st.motion_refusal() == {"status": "error", "message": _TEXT_PARKING}
    assert st.begin_sync() is False


# --------------------------------------------------------------------------------------------------
# ParkMachine
# --------------------------------------------------------------------------------------------------


def test_step_of_closed_park_does_nothing() -> None:
    st = _state()
    f = _Fakes(st)
    m = f.machine()
    _begin(st)
    m.accept(1, 30.0)
    m.step(_HOME, True)
    assert f.pubs[-1]["state"] == "done" and f.pubs[-1]["home"] == "already"
    pubs, servo = len(f.pubs), f.servo_calls
    _begin(st)  # park 2 без accept
    m.step(_HOME, True)
    assert (len(f.pubs), f.servo_calls, f.launches) == (pubs, servo, [])


def test_stale_launch_return_does_not_mark_new_park() -> None:
    st = _state()
    f = _Fakes(st)
    m = f.machine()
    entered, release = threading.Event(), threading.Event()

    def slow_launch(seq: int) -> dict:
        if seq == 1:
            entered.set()
            assert release.wait(_JOIN_S)
            return {"status": "ok"}  # поздний «ok» park 1
        return f.launch_ok(seq)

    f.launch_fn = slow_launch
    _begin(st)
    m.accept(1, 30.0)
    t = _in_thread(lambda: m.step(_AWAY, True))
    assert entered.wait(_JOIN_S)
    m.abort("закрыт тестом")
    _begin(st)
    m.accept(2, 30.0)
    release.set()
    t.join(_JOIN_S)
    assert not t.is_alive()
    m.step(_AWAY, True)
    assert f.launches.count(2) == 1
    seq2 = [p for p in f.pubs if p["seq"] == 2]
    assert all(p["state"] == "parking" for p in seq2), seq2
    assert all(p["reason"] != _TEXT_HOME_FAILED for p in f.pubs)


def test_stale_finisher_does_not_close_new_park() -> None:
    st = _state()
    f = _Fakes(st)
    m = f.machine()
    entered, release = threading.Event(), threading.Event()

    def slow_servo() -> bool:
        entered.set()
        assert release.wait(_JOIN_S)
        return True

    f.servo_fn = slow_servo
    _begin(st)
    m.accept(1, 30.0)
    t = _in_thread(lambda: m.step(_HOME, True))
    assert entered.wait(_JOIN_S)
    m.abort("закрыт тестом")
    _begin(st)
    m.accept(2, 30.0)
    release.set()
    t.join(_JOIN_S)
    assert not t.is_alive()
    v = st.park_view()
    assert (v.parking, v.seq) == (True, 2)
    assert [p for p in f.pubs if p["seq"] == 2 and p["state"] == "done"] == []


def test_no_parking_publish_after_terminal() -> None:
    st = _state()
    f = _Fakes(st)
    m = f.machine()
    entered, release = threading.Event(), threading.Event()

    def slow_launch(seq: int) -> dict:
        entered.set()
        assert release.wait(_JOIN_S)
        return {"status": "ok"}

    f.launch_fn = slow_launch
    _begin(st)
    m.accept(1, 30.0)
    t = _in_thread(lambda: m.step(_AWAY, True))
    assert entered.wait(_JOIN_S)
    m.abort("закрыт тестом")
    release.set()
    t.join(_JOIN_S)
    assert not t.is_alive()
    m.step(_AWAY, True)
    assert f.pubs[-1]["state"] == "failed"
    assert f.pubs[-1]["reason"] == "закрыт тестом"


def test_shutdown_freezes_machine() -> None:
    st = _state()
    f = _Fakes(st)
    m = f.machine()
    at_launch: list[int] = []

    def launch_during_shutdown(seq: int) -> dict:
        at_launch.append(len(f.pubs))
        st.request_stop_begin()  # выключение пришло на шаге home
        return {"status": "error", "message": _TEXT_STOPPING}

    f.launch_fn = launch_during_shutdown
    _begin(st)
    m.accept(1, 30.0)
    m.step(_AWAY, True)
    assert at_launch and len(f.pubs) == at_launch[0]  # поздний отказ запуска — без записи
    m.step(_AWAY, True)
    m.guard(False)
    m.abort("идёт отключение робота")
    assert len(f.pubs) == at_launch[0]
    m.abort(_TEXT_STOPPING, stop=True)
    assert len(f.pubs) == at_launch[0] + 1
    last = f.pubs[-1]
    assert (last["state"], last["step"], last["reason"]) == ("failed", "home", _TEXT_STOPPING)


def test_home_program_link_failure_gives_link_reason() -> None:
    """Поток программы дома увидел обрыв раньше guard тика: исход «link» -> «связь с роботом потеряна» (А8)."""
    st = _state()
    f = _Fakes(st)
    m = f.machine()
    _begin(st)
    m.accept(1, 30.0)
    m.step(_AWAY, True)
    assert f.launches == [1]
    st.program_finished("park", False, "link")
    m.step(_AWAY, True)
    last = f.pubs[-1]
    assert (last["state"], last["step"], last["reason"]) == ("failed", "home", "связь с роботом потеряна")
