"""Тесты автора T5.3e.5a (REDS 5a1): ``DeviceManager.robot_park_all``, ``RobotDriverV2.park_wait``, ``wait_terminal``.

Purpose:
    Хазарды ожидания итогов: срок ответа поверх тика, опрос ``should_stop`` перед каждым роботом и в каждом срезе,
    завершающий проход, пробуждение ждущего до публикации, память 8 терминалов, присоединение к park оператора на
    настоящем драйвере, стоп драйвера во время ожидания. Блокирующие вызовы — daemon-поток с дедлайном.

Public API:
    Только тесты ``test_*``.

Stability: lite
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from typing import Any

import pytest

from multiprocess_framework.modules.base_manager import open_scope

from Services.device_hub.drivers.base import BaseDeviceDriver
from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2
from Services.device_hub.drivers.robot_driver_v2.park import ParkMachine
from Services.device_hub.drivers.robot_driver_v2.state import RobotState
from Services.device_hub.manager import DeviceManager
from Services.device_hub.tests.conftest import FakeClock
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.programs import Point
from Services.robot_comm.tests.e2e_rig_v2 import E2eRig, bounded, pulse

pytestmark = pytest.mark.timeout(90)

TEXT_PARKING = "идёт основная остановка робота"
TEXT_STOPPING = "драйвер робота останавливается"
TEXT_NOT_DONE = "основная остановка не выполнена: "
_CALL_S = 15.0
_SCOPE: Any = None


@pytest.fixture(autouse=True)
def driver_scope() -> Iterator[Any]:
    global _SCOPE
    scope = open_scope("rv2parkallauth", budget_s=6.0)
    _SCOPE = scope
    try:
        yield scope
    finally:
        _SCOPE = None
        report = scope.close()
        assert list(report.survivors) == [], f"выжившие потоки: {list(report.survivors)}"


def _done(seq: int = 1, home: str = "moved") -> dict:
    return {
        "seq": seq,
        "state": "done",
        "step": "servo",
        "home": home,
        "servo": False,
        "dropped": {"jobs": 0, "returns": 0},
        "reason": None,
        "elapsed_s": 0.4,
    }


class _Fake(BaseDeviceDriver):
    """Поддельный робот: ``park`` по сценарию, ``park_wait`` спит свой срез, если итога нет."""

    kind = "robot"

    def __init__(self, entry: Any, protocol: Any = None) -> None:
        super().__init__(entry, protocol)
        self.up = False
        self.park_calls: list[dict] = []
        self.reply: dict = {"status": "ok", "accepted": True, "seq": 1, "timeout_s": 30.0}
        self.raises: Exception | None = None
        self.hold_s = 0.0
        self.terminal: dict | None = None
        self.on_wait: Callable[[float], None] | None = None

    def initialize(self) -> bool:
        self.is_initialized = True
        return True

    def connect(self) -> bool:
        self.up = True
        return True

    def disconnect(self) -> None:
        self.up = False

    @property
    def is_connected(self) -> bool:
        return self.up

    def tick(self, stop_event: Any = None) -> None:
        return None

    def call(self, op: str, args: dict) -> dict:
        if op != "park":
            return {"status": "ok"}
        self.park_calls.append(dict(args))
        if self.hold_s:
            time.sleep(self.hold_s)
        if self.raises is not None:
            raise self.raises
        return dict(self.reply)

    def park_current_seq(self) -> int:
        return 5

    def park_wait(self, seq: int, timeout_s: float) -> dict | None:
        if self.on_wait is not None:
            self.on_wait(timeout_s)
        if self.terminal is not None:
            return dict(self.terminal)
        time.sleep(max(timeout_s, 0.0))
        return None


class _Hub:
    def __init__(self) -> None:
        self.builders: dict[str, Callable[[Any], Any]] = {}
        self.mgr = DeviceManager(None, lambda _p, _v: None, spawn=_SCOPE.spawn)
        self.mgr.register_driver_factory("robot", lambda entry, _proto: self.builders[entry.id](entry))
        assert self.mgr.initialize() is True

    def fake(self, dev_id: str, *, protocol: str = "delta_v2", connect: bool = True) -> _Fake:
        box: dict[str, _Fake] = {}

        def build(entry: Any) -> _Fake:
            box["d"] = _Fake(entry)
            return box["d"]

        self.builders[dev_id] = build
        self.mgr.upsert(
            {
                "id": dev_id,
                "name": dev_id,
                "kind": "robot",
                "protocol": protocol,
                "transport": {"type": "tcp", "host": "127.0.0.1", "port": 50998, "unit_id": 2},
            }
        )
        if connect:
            assert self.mgr.connect(dev_id) is True
            return box["d"]
        return build(self.mgr.get(dev_id))

    def park_all(self, args: dict, should_stop: Callable[[], bool] | None = None) -> tuple[dict, float]:
        t0 = time.monotonic()
        if should_stop is None:
            answer = bounded(lambda: self.mgr.robot_park_all(dict(args)), 20.0)
        else:
            answer = bounded(lambda: self.mgr.robot_park_all(dict(args), should_stop=should_stop), 20.0)
        return answer, time.monotonic() - t0


def _after(delay_s: float) -> Callable[[], bool]:
    t_end = time.monotonic() + delay_s
    return lambda: time.monotonic() >= t_end


# --------------------------------------------------------------------------------------------------
# Сценарный робот
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("case", ["two_done", "error_refused_done"])
def test_outcomes_per_robot(case: str) -> None:
    """(а) два v2 ``done`` -> ``ok``; (б) исключение -> ``error``, иной отказ -> ``refused``, третий ``done``."""
    h = _Hub()
    if case == "two_done":
        for dev_id in ("r1", "r2"):
            h.fake(dev_id).terminal = _done()
        answer, _ = h.park_all({})
        assert answer["status"] == "ok", answer
        assert {k: v["result"] for k, v in answer["robots"].items()} == {"r1": "done", "r2": "done"}, answer
        assert "message" not in answer, answer
        return
    h.fake("r1").raises = RuntimeError("x")
    h.fake("r2").reply = {"status": "error", "message": "m2"}
    h.fake("r3").terminal = _done()
    answer, _ = h.park_all({})
    assert isinstance(answer, dict)
    assert answer["robots"]["r1"] == {"result": "error", "message": "RuntimeError: x"}, answer
    assert answer["robots"]["r2"] == {"result": "refused", "message": "m2"}, answer
    assert answer["robots"]["r3"] == {"result": "done", "seq": 1, "home": "moved", "elapsed_s": 0.4}, answer
    assert answer["status"] == "error", answer
    assert answer["message"] == TEXT_NOT_DONE + "r1, r2", answer


def test_reply_bounded_when_no_terminal() -> None:
    """``timeout_s 1.0``, итога нет: ответ за [2,4; 2,9] с, ``timeout``, ``status "error"``."""
    h = _Hub()
    h.fake("r1")
    answer, took = h.park_all({"timeout_s": 1.0})
    assert 2.4 <= took <= 2.9, took
    assert answer["robots"]["r1"] == {"result": "timeout", "seq": 1}, answer
    assert answer["status"] == "error", answer


@pytest.mark.parametrize("bad", [0.5, 33, True, "30"])
def test_bad_timeout_refused_robots_untouched(bad: Any) -> None:
    h = _Hub()
    robot = h.fake("r1")
    robot.terminal = _done()
    answer, _ = h.park_all({"timeout_s": bad})
    assert answer == {"status": "error", "message": "timeout_s: число от 1 до 32"}, answer
    assert robot.park_calls == []


def test_skipped_order_v1_then_link() -> None:
    """v1 подключённый и v1 без связи -> ``not_v2`` (протокол раньше связи); v2 без связи -> ``not_connected``."""
    h = _Hub()
    up = h.fake("a_v1", protocol="delta_universal3")
    h.fake("b_v1", protocol="delta_universal3", connect=False)
    h.fake("c_v2", connect=False)
    answer, _ = h.park_all({})
    assert answer["robots"] == {
        "a_v1": {"result": "skipped", "reason": "not_v2"},
        "b_v1": {"result": "skipped", "reason": "not_v2"},
        "c_v2": {"result": "skipped", "reason": "not_connected"},
    }, answer
    assert answer["status"] == "ok", answer
    assert up.park_calls == []


def test_should_stop_ends_wait_quickly_three_robots() -> None:
    """Три ждущих, ``should_stop`` истинно через 0,25 с (середина среза) -> ответ ≤ 1,0 с, все ``timeout``."""
    h = _Hub()
    robots = [h.fake(dev_id) for dev_id in ("r1", "r2", "r3")]
    answer, took = h.park_all({}, should_stop=_after(0.25))
    assert took <= 1.0, took
    assert all(len(r.park_calls) == 1 for r in robots)
    assert {v["result"] for v in answer["robots"].values()} == {"timeout"}, answer
    assert answer["status"] == "error", answer


def test_should_stop_during_send_skips_rest() -> None:
    """Отправка первому держит 1,5 с, стоп через 0,3 с: второму и третьему ``stopping``; реестр не по алфавиту."""
    h = _Hub()
    third = h.fake("r3")
    first = h.fake("r1")
    second = h.fake("r2")
    first.hold_s = 1.5
    answer, took = h.park_all({}, should_stop=_after(0.3))
    assert took <= 1.5 + 0.7, took
    assert answer["robots"]["r2"] == {"result": "skipped", "reason": "stopping"}, answer
    assert answer["robots"]["r3"] == {"result": "skipped", "reason": "stopping"}, answer
    assert second.park_calls == [] and third.park_calls == []
    assert answer["status"] == "error", answer
    assert answer["message"] == TEXT_NOT_DONE + "r1, r2, r3", answer


def test_final_pass_catches_late_terminal() -> None:
    """Итог ``a`` ставится в срезе ``b``, который кончается за сроком: в цикле ``a`` больше не опрашивается."""
    h = _Hub()
    a = h.fake("a")
    b = h.fake("b")
    t_start = time.monotonic()

    def late(timeout_s: float) -> None:
        # Срез b в цикле (не завершающий проход) после 2,0 с из 2,5: итог a, затем b спит за срок ожидания
        if timeout_s > 0 and a.terminal is None and time.monotonic() - t_start >= 2.0:
            a.terminal = _done()
            time.sleep(0.6)

    b.on_wait = late
    answer, took = h.park_all({"timeout_s": 1.0})
    assert answer["robots"]["a"]["result"] == "done", answer
    assert answer["robots"]["b"] == {"result": "timeout", "seq": 1}, answer
    assert took <= 3.4, took


def test_timeout_s_sent_as_float_and_echoed_as_float() -> None:
    h = _Hub()
    robot = h.fake("r1")
    robot.terminal = _done()
    answer, _ = h.park_all({"timeout_s": 5})
    assert robot.park_calls == [{"timeout_s": 5.0}] and type(robot.park_calls[0]["timeout_s"]) is float
    assert answer["timeout_s"] == 5.0 and type(answer["timeout_s"]) is float, answer


def test_joined_by_current_seq() -> None:
    h = _Hub()
    robot = h.fake("r1")
    robot.reply = {"status": "error", "message": TEXT_PARKING}
    robot.terminal = _done(seq=5, home="already")
    answer, _ = h.park_all({})
    assert answer["robots"]["r1"] == {
        "result": "done",
        "seq": 5,
        "home": "already",
        "elapsed_s": 0.4,
        "joined": True,
    }, answer


def test_wait_exception_is_error_and_neighbour_finishes() -> None:
    """Исключение ``park_wait`` одного робота -> его ``error``; сосед доходит до ``done``; ответ — словарь."""
    h = _Hub()
    broken = h.fake("r1")

    def boom(_t: float) -> None:
        raise RuntimeError("wait")

    broken.on_wait = boom
    h.fake("r2").terminal = _done()
    answer, _ = h.park_all({"timeout_s": 1.0})
    assert answer["robots"]["r1"] == {"result": "error", "message": "RuntimeError: wait"}, answer
    assert answer["robots"]["r2"]["result"] == "done", answer


# --------------------------------------------------------------------------------------------------
# ParkMachine.wait_terminal
# --------------------------------------------------------------------------------------------------


def _machine(publish: Callable[[dict], None]) -> tuple[ParkMachine, RobotState]:
    clock = FakeClock()
    state = RobotState(clock=clock.clock, queue_maxlen=8)
    machine = ParkMachine(
        state=state,
        clock=clock.clock,
        publish=publish,
        home_point=lambda: Point(300.0, 0.0, 0.0, 0.0),
        launch_home=lambda _seq: {"status": "ok"},
        servo_off=lambda: True,
        heartbeat=lambda: None,
        record_err=lambda: None,
        log_id="rwait",
    )
    return machine, state


def _terminal_now(machine: ParkMachine, state: RobotState, reason: str = "r") -> int:
    seq = state.park_begin().seq
    assert seq > 0
    machine.fail(seq, reason)
    return seq


def test_wait_terminal_returns_fast() -> None:
    """(а) итог до вызова -> ≤ 0,1 с; (б) ждущий спит ≥ 0,1 с, ``fail`` с бросающим ``publish`` -> ≤ 0,1 с."""
    machine, state = _machine(lambda _v: None)
    seq = _terminal_now(machine, state, "до")
    t0 = time.monotonic()
    got = bounded(lambda: machine.wait_terminal(seq, 5.0), 10.0)
    assert time.monotonic() - t0 <= 0.1
    assert got is not None and (got["seq"], got["state"], got["reason"]) == (seq, "failed", "до"), got

    def broken(_v: dict) -> None:
        raise RuntimeError("publish")

    machine, state = _machine(broken)
    seq = state.park_begin().seq
    box: dict[str, Any] = {}

    def waiter() -> None:
        box["v"] = machine.wait_terminal(seq, 5.0)
        box["t"] = time.monotonic()

    thread = threading.Thread(target=waiter, daemon=True)
    thread.start()
    time.sleep(0.15)
    assert thread.is_alive()
    t_fail = time.monotonic()
    with pytest.raises(RuntimeError):
        machine.fail(seq, "после")
    thread.join(5.0)
    assert not thread.is_alive()
    assert box["t"] - t_fail <= 0.1, box["t"] - t_fail
    assert box["v"]["state"] == "failed" and box["v"]["reason"] == "после", box


def test_wait_terminal_none_by_deadline_and_negative_timeout() -> None:
    machine, _state = _machine(lambda _v: None)
    t0 = time.monotonic()
    assert machine.wait_terminal(1, 0.3) is None
    assert 0.25 <= time.monotonic() - t0 <= 1.0
    t0 = time.monotonic()
    assert machine.wait_terminal(1, -5.0) is None
    assert time.monotonic() - t0 <= 0.1


def test_wait_terminal_keeps_last_eight_evicting_several() -> None:
    """11 терминалов подряд: три наименьших вытеснены, 8 последних на месте (вытеснение — не одна запись)."""
    machine, state = _machine(lambda _v: None)
    seqs = [_terminal_now(machine, state) for _ in range(11)]
    assert seqs == list(range(1, 12))
    assert [machine.wait_terminal(s, 0.0) is None for s in seqs] == [True] * 3 + [False] * 8


def test_wait_terminal_returns_copy() -> None:
    machine, state = _machine(lambda _v: None)
    seq = _terminal_now(machine, state)
    first = machine.wait_terminal(seq, 0.0)
    assert first is not None
    first["state"] = "x"
    first["dropped"]["jobs"] = 99
    again = machine.wait_terminal(seq, 0.0)
    assert again is not None and again["state"] == "failed" and again["dropped"]["jobs"] == 0, again


# --------------------------------------------------------------------------------------------------
# Настоящий драйвер над E2eRig
# --------------------------------------------------------------------------------------------------


class _Spy(RobotDriverV2):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.parks: list[dict] = []
        self.sent = threading.Event()

    def call(self, op: str, args: dict) -> dict:
        reply = super().call(op, args)
        if op == "park":
            self.parks.append(reply)
            self.sent.set()
        return reply


@contextmanager
def _real() -> Iterator[tuple[_Hub, _Spy, E2eRig]]:
    with ExitStack() as stack:
        rig = stack.enter_context(E2eRig())
        clock = FakeClock()
        h = _Hub()
        h.builders["r1"] = lambda entry: _Spy(entry, clock=clock.clock, sleep=clock.sleep, spawn=_SCOPE.spawn)
        h.mgr.upsert(
            {
                "id": "r1",
                "name": "r1",
                "kind": "robot",
                "protocol": "delta_v2",
                "transport": {"type": "tcp", "host": "127.0.0.1", "port": rig.port, "unit_id": ROBOT_UNIT_ID},
            }
        )
        assert bounded(lambda: h.mgr.connect("r1"), 60.0) is True
        drv = h.mgr.get_driver("r1")
        assert isinstance(drv, _Spy)
        drv.desired_connected = True
        try:
            yield h, drv, rig
        finally:
            try:
                bounded(drv.disconnect, _CALL_S)
            except Exception:  # noqa: BLE001 — уборка не подменяет исключение теста
                pass


def _off_home(drv: RobotDriverV2, rig: E2eRig) -> None:
    assert bounded(lambda: drv.call("jog_step", {"dx": 80, "dy": 0, "spd": 50}), _CALL_S)["status"] == "ok"
    end = time.monotonic() + 10
    while not (abs(rig.pose_wire()[0] - 380.0) <= 0.05 and rig.read("TLM_MOVING") == [0]):
        assert time.monotonic() < end, "робот не встал в x == 380"
        time.sleep(0.02)


def _background(h: _Hub, should_stop: Callable[[], bool] = lambda: False) -> tuple[threading.Thread, dict]:
    box: dict[str, Any] = {}

    def body() -> None:
        box["answer"] = h.mgr.robot_park_all({}, should_stop=should_stop)
        box["t"] = time.monotonic()

    thread = threading.Thread(target=body, name="park-all-auth", daemon=True)
    thread.start()
    return thread, box


def test_real_driver_joined_and_moved() -> None:
    """Park оператора идёт (тика нет): хаб присоединяется к его ``seq``; с тиком — ``done/moved``, ``joined``."""
    with _real() as (h, drv, rig):
        _off_home(drv, rig)
        operator = bounded(lambda: drv.call("park", {}), _CALL_S)
        assert operator["accepted"] is True, operator
        drv.sent.clear()
        thread, box = _background(h)
        assert drv.sent.wait(5.0)
        assert drv.parks[-1] == {"status": "error", "message": TEXT_PARKING}, drv.parks
        with pulse(drv.tick, 0.05):
            thread.join(15.0)
        assert not thread.is_alive()
        robot = box["answer"]["robots"]["r1"]
        assert (robot["result"], robot["seq"], robot["home"], robot.get("joined")) == (
            "done",
            operator["seq"],
            "moved",
            True,
        ), robot


def test_real_driver_park_all_then_request_stop() -> None:
    """Хаб ждёт итог (тика нет), стоп драйвера из другого потока -> ``failed``, «драйвер робота останавливается»."""
    with _real() as (h, drv, _rig):
        thread, box = _background(h)
        assert drv.sent.wait(5.0)
        time.sleep(0.3)
        bounded(lambda: drv.request_stop(time.monotonic() + 2.5), _CALL_S)
        t_stop = time.monotonic()
        thread.join(5.0)
        assert not thread.is_alive()
        assert box["t"] - t_stop <= 0.5, box["t"] - t_stop
        robot = box["answer"]["robots"]["r1"]
        assert (robot["result"], robot["reason"]) == ("failed", TEXT_STOPPING), robot
