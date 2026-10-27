"""Тесты автора T5.3e.1 (бриф 1b): команда ``park`` и автомат в тике драйвера v2 над ``E2eRig``.

Purpose:
    Хазарды проводки: пометки release и SOFT до ``accept``, окна ``jog_hold`` (между проверкой и допуском, JOG_CONT в
    полёте), стоп оператора до запуска хода домой, ``guard`` до раннего выхода тика, итог ``request_stop`` после
    записи HARD, длительность тика. Швы — обёртки публичных методов ``drv.state.*``; приватные поля не читаются.

Public API:
    Только тесты ``test_*``.

Stability: lite
"""

from __future__ import annotations

import logging
import re
import statistics
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import pytest

from multiprocess_framework.modules.base_manager import open_scope

from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2
from Services.device_hub.registry.entry import DeviceEntry
from Services.device_hub.tests.conftest import FakeClock
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.programs import Move, Point, Program
from Services.robot_comm.tests.e2e_rig_v2 import E2eRig, bounded

DEV = "rtick"
TEXT_PARKING = "идёт основная остановка робота"
TEXT_STOPPING = "драйвер робота останавливается"
TEXT_CANCELLED = "прервано стопом оператора"
TEXT_LINK = "связь с роботом потеряна"
_LEASE_MARK = "jog остановлен поводком"
_LOGGER = "mpf.Services.device_hub.drivers.base"
_JOG = {"dir": 1, "spd": 20}
_CALL_S = 15.0
_WAIT_S = 5.0
_STOP_LINE = re.compile(r"^W STOP_REQ = (\d+)$")
_SCOPE: Any = None


@pytest.fixture(autouse=True)
def driver_scope() -> Iterator[Any]:
    global _SCOPE
    scope = open_scope("rv2parktick", budget_s=6.0)
    _SCOPE = scope
    try:
        yield scope
    finally:
        _SCOPE = None
        report = scope.close()
        assert list(report.survivors) == [], f"выжившие потоки: {list(report.survivors)}"


class _Rec:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: list[tuple[str, Any]] = []
        self.hooks: list[Callable[[str, Any], None]] = []

    def __call__(self, path: str, payload: Any) -> None:
        with self._lock:
            self._items.append((path, payload))
        for hook in list(self.hooks):
            hook(path, payload)

    def at(self, leaf: str) -> list[Any]:
        path = f"devices.state.{DEV}.{leaf}"
        with self._lock:
            return [p for k, p in self._items if k == path]


@dataclass
class _Env:
    drv: RobotDriverV2
    rig: E2eRig
    rec: _Rec
    clock: FakeClock


@contextmanager
def _env(fake_clock: FakeClock) -> Iterator[_Env]:
    rec = _Rec()
    with E2eRig() as rig:
        entry = DeviceEntry(
            id=DEV,
            name=DEV,
            kind="robot",
            protocol="delta_v2",
            transport={"type": "tcp", "host": "127.0.0.1", "port": rig.port, "unit_id": ROBOT_UNIT_ID},
            params={"robot_params": {"P_SPD_DEFAULT": 10}},  # ход домой длиннее вмешательств теста
        )
        drv = RobotDriverV2(entry, clock=fake_clock.clock, sleep=fake_clock.sleep, publish=rec, spawn=_SCOPE.spawn)
        assert bounded(drv.connect, 60.0) is True
        drv.desired_connected = True
        try:
            yield _Env(drv, rig, rec, fake_clock)
        finally:
            try:
                bounded(drv.disconnect, _CALL_S)
            except Exception:  # noqa: BLE001 — уборка не подменяет исключение теста
                pass


def _call(e: _Env, op: str, args: dict | None = None) -> dict:
    return bounded(lambda: e.drv.call(op, dict(args or {})), _CALL_S)


def _until(pred: Callable[[], object], deadline_s: float, what: str) -> None:
    end = time.monotonic() + deadline_s
    while not pred():
        if time.monotonic() >= end:
            raise AssertionError(f"не дождались за {deadline_s} с: {what}")
        time.sleep(0.02)


def _levels(e: _Env, since: int) -> list[int]:
    answer = e.drv.call("exchange_log_get", {"since_seq": since, "limit": 2000})
    out: list[int] = []
    for line in answer["lines"]:
        m = _STOP_LINE.match(line["text"])
        if m:
            out.extend([int(m.group(1)) & 3] * line["n"])
    return out


def _mark(e: _Env) -> int:
    return e.drv.call("exchange_log_get", {"since_seq": 0, "limit": 1})["last_seq"] + 1


def _jog_conts(e: _Env) -> int:
    return sum(1 for _, text in e.rig.core.events() if "op=JOG_CONT" in text)


def _off_home(e: _Env) -> None:
    assert _call(e, "jog_step", {"dx": 80, "dy": 0, "spd": 50})["status"] == "ok"
    _until(lambda: abs(e.rig.pose_wire()[0] - 380.0) <= 0.05 and e.rig.read("TLM_MOVING") == [0], 10, "x == 380")


def _hold(e: _Env) -> None:
    assert _call(e, "jog_hold", _JOG)["status"] == "ok"
    _until(lambda: e.rig.read("TLM_MOVING") == [1], _WAIT_S, "jog едет")


def _lease_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [m for m in (r.getMessage() for r in caplog.records) if _LEASE_MARK in m]


def _last_park(e: _Env) -> dict | None:
    values = e.rec.at("park")
    return values[-1] if values else None


def _start_home(e: _Env) -> None:
    _off_home(e)
    assert _call(e, "park")["accepted"] is True
    bounded(e.drv.tick, _CALL_S)
    _until(lambda: e.rig.read("TLM_MOVING") == [1], 10, "ход домой")


def test_park_begin_marks_lease_released(fake_clock: FakeClock, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger=_LOGGER), _env(fake_clock) as e:
        _hold(e)
        since = _mark(e)
        assert _call(e, "park")["accepted"] is True
        e.clock.t += 0.3  # окно удержания истекло бы до 1-го тика
        time.sleep(0.4)
        assert _lease_lines(caplog) == []
        assert _levels(e, since) == [1]


@pytest.mark.parametrize("scene", ["jog", "program"])
def test_park_accepted_only_after_release_and_soft(scene: str, fake_clock: FakeClock) -> None:
    with _env(fake_clock) as e:
        if scene == "jog":
            _hold(e)
        else:
            points = {
                "a": Point(name="a", x=400, y=100, z=-60, rz=0, hand=1),
                "b": Point(name="b", x=300, y=-210, z=-40, rz=-100, hand=1),
            }
            program = Program(name="user", steps=tuple(Move(point="ab"[i % 2], kind="JOINT") for i in range(4)))
            assert e.drv.start_program(program, points, None, name="user")["status"] == "ok"
            _until(lambda: e.rig.read("TLM_MOVING") == [1], _WAIT_S, "программа едет")
        since = _mark(e)
        at_first: list[list[int]] = []

        def on_publish(path: str, payload: Any) -> None:
            if path.endswith(".park") and not at_first:
                at_first.append(_levels(e, since))

        e.rec.hooks.append(on_publish)
        assert _call(e, "park")["accepted"] is True
        assert at_first and 1 in at_first[0], at_first


def test_jog_hold_admit_rechecks_parking(fake_clock: FakeClock) -> None:
    with _env(fake_clock) as e:
        st = e.drv.state
        original = st.jog_hold_check
        in_window, release = threading.Event(), threading.Event()

        def check_then_wait() -> Any:
            decision = original()
            in_window.set()
            assert release.wait(_WAIT_S)
            return decision

        st.jog_hold_check = check_then_wait
        replies: list[dict] = []
        holder = threading.Thread(target=lambda: replies.append(e.drv.call("jog_hold", dict(_JOG))), daemon=True)
        holder.start()
        assert in_window.wait(_WAIT_S)
        assert _call(e, "park")["accepted"] is True
        conts = _jog_conts(e)
        release.set()
        holder.join(_CALL_S)
        assert replies == [{"status": "error", "message": TEXT_PARKING}]
        assert _jog_conts(e) == conts


def test_jog_cont_in_flight_then_park_no_lease_soft(fake_clock: FakeClock, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger=_LOGGER), _env(fake_clock) as e:
        st = e.drv.state
        original = st.jog_started
        in_window, release = threading.Event(), threading.Event()

        def wait_then_start(run: Any) -> bool:
            in_window.set()
            assert release.wait(_WAIT_S)
            return original(run)

        st.jog_started = wait_then_start
        replies: list[dict] = []
        holder = threading.Thread(target=lambda: replies.append(e.drv.call("jog_hold", dict(_JOG))), daemon=True)
        holder.start()
        assert in_window.wait(_WAIT_S)
        assert _call(e, "park")["accepted"] is True
        release.set()
        holder.join(_CALL_S)
        assert replies == [{"status": "error", "message": TEXT_STOPPING}]
        e.clock.t += 0.3
        time.sleep(0.4)
        assert _lease_lines(caplog) == []
        assert e.drv.state.view().jog.active is False  # поток поводка не запущен


def test_operator_stop_cancels_park_before_home_launch(fake_clock: FakeClock) -> None:
    with _env(fake_clock) as e:
        _off_home(e)
        st = e.drv.state
        original = st.admit_launch

        def stop_then_admit(connected: Any, **kw: Any) -> Any:
            if kw.get("kind") == "park":
                assert e.drv.call("stop", {"level": "HARD"})["status"] == "ok"
            return original(connected, **kw)

        st.admit_launch = stop_then_admit
        assert _call(e, "park")["accepted"] is True
        for _ in range(2):
            bounded(e.drv.tick, _CALL_S)
        final = _last_park(e)
        assert final is not None and (final["state"], final["reason"]) == ("failed", TEXT_CANCELLED)
        assert [p for p in e.rec.at("program") if p.get("name") == "park_home"] == []


def test_guard_runs_before_early_exit_on_link_loss(fake_clock: FakeClock) -> None:
    with _env(fake_clock) as e:
        _start_home(e)
        bounded(e.rig.restart, 20.0)
        final = None
        for _ in range(2):
            time.sleep(0.3)
            bounded(e.drv.tick, _CALL_S)
            final = _last_park(e)
            if final is not None and final["state"] != "parking":
                break
        assert final is not None and (final["state"], final["reason"]) == ("failed", TEXT_LINK)
        assert e.drv.is_connected is False  # итог поставлен тиком, который до переподключения не дошёл


def test_request_stop_publishes_failed_after_stop_write(fake_clock: FakeClock) -> None:
    with _env(fake_clock) as e:
        _start_home(e)
        since = _mark(e)
        at_failed: list[list[int]] = []

        def on_publish(path: str, payload: Any) -> None:
            if path.endswith(".park") and payload.get("state") == "failed":
                at_failed.append(_levels(e, since))

        e.rec.hooks.append(on_publish)
        bounded(lambda: e.drv.request_stop(time.monotonic() + 2.5), _CALL_S)
        assert at_failed and 2 in at_failed[0], at_failed
        final = _last_park(e)
        assert final is not None and (final["state"], final["reason"]) == ("failed", TEXT_STOPPING)


def test_tick_duration_during_park(fake_clock: FakeClock) -> None:
    with _env(fake_clock) as e:
        _start_home(e)
        durations: list[float] = []
        for _ in range(10):
            t0 = time.perf_counter()
            bounded(e.drv.tick, _CALL_S)
            durations.append(time.perf_counter() - t0)
        assert statistics.median(durations) <= 0.1, durations


def test_servo_step_after_shutdown_begin_writes_no_servo(fake_clock: FakeClock) -> None:
    """Выключение началось между решением шага ``servo`` и записью: SERVO 0 не пишется (серво sim остаётся ON)."""
    with _env(fake_clock) as e:
        assert e.rig.read("TLM_SERVO") == [1]
        assert _call(e, "park")["accepted"] is True  # робот дома: шаг servo в первом же тике
        st = e.drv.state
        original = st.park_view
        calls = [0]

        def view_then_shutdown() -> Any:
            v = original()
            calls[0] += 1
            if calls[0] == 2:  # 1-й — guard, 2-й — шаг: решение «servo» по срезу до выключения
                st.request_stop_begin()
            return v

        st.park_view = view_then_shutdown
        bounded(e.drv.tick, _CALL_S)
        time.sleep(0.3)
        assert calls[0] >= 2
        assert e.rig.read("TLM_SERVO") == [1]
        assert [p for p in e.rec.at("park") if p["state"] == "done"] == []
