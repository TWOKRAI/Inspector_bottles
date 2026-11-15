# -*- coding: utf-8 -*-
"""Hazard-тесты сеанса `DeviceSession` (Task 2.1, автор — исполнитель): гонки start/stop, дедлайн, колбэки.

Ожидаемые значения — литералы из ACCEPTANCE задачи 2.1. Всё, что может зависнуть, идёт в daemon-потоке
с дедлайном `join`; в teardown фикстуры каждый сеанс останавливается и его потоки ждутся.
"""

from __future__ import annotations

import threading
import time

import pytest

from Services.camera_device.session import DeviceSession
from Services.camera_device.testing.fake_port import make_port

OPEN_THEN_CLOSE = ["acquire", "enum_devices", "open", "close", "release"]


def _names(port) -> list[str]:
    return [call[0] for call in list(port.calls)]


def _await(pred, message: str, deadline: float = 2.0) -> None:
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if pred():
            return
        time.sleep(0.005)
    assert pred(), f"не дождались за {deadline} с: {message}"


def _in_thread(fn, box: dict, key: str) -> threading.Thread:
    """Запустить `fn` в daemon-потоке; результат и длительность — в `box[key]`."""

    def run() -> None:
        t0 = time.perf_counter()
        box[key] = (fn(), time.perf_counter() - t0)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


class _Rig:
    def __init__(self) -> None:
        self._before = set(threading.enumerate())
        self.sessions: list[DeviceSession] = []
        self.states: list[tuple[str, str]] = []
        self.frames: list = []

    def make(self, *, on_frame=None, on_state=None, on_stall=None, timeout_ms=500, watchdog_s=5.0, **port_opts):
        port_opts.setdefault("frame_period_s", 0.01)
        port = make_port(**port_opts)

        def state_cb(old: str, new: str) -> None:
            self.states.append((old, new))
            if on_state is not None:
                on_state(old, new)

        def frame_cb(frame) -> None:
            self.frames.append(frame)
            if on_frame is not None:
                on_frame(frame)

        session = DeviceSession(
            port,
            port.sdk,
            None,
            timeout_ms=timeout_ms,
            watchdog_s=watchdog_s,
            on_frame=frame_cb,
            on_state=state_cb,
            on_stall=on_stall,
        )
        self.sessions.append(session)
        return port, session

    def teardown(self) -> None:
        for session in self.sessions:
            stopper = threading.Thread(target=session.stop, args=(2.0,), daemon=True)
            stopper.start()
            stopper.join(5.0)
        me = threading.current_thread()
        for thread in threading.enumerate():
            if thread not in self._before and thread is not me and thread.daemon:
                thread.join(3.0)


@pytest.fixture
def rig():
    r = _Rig()
    yield r
    r.teardown()


@pytest.mark.timeout(20)
def test_старт_прерван_стопом(rig):
    port, session = rig.make(open_delay_s=0.5)
    box: dict = {}
    a = _in_thread(lambda: session.start(5.0), box, "a")
    time.sleep(0.05)
    b = _in_thread(lambda: session.stop(2.0), box, "b")
    time.sleep(0.05)
    c = _in_thread(lambda: session.start(0.1), box, "c")
    for thread in (a, b, c):
        thread.join(5.0)
        assert not thread.is_alive()

    assert box["a"][0] is False
    assert box["c"][0] is False
    assert box["c"][1] < 0.05, "start() во время stopping отказывает по состоянию, а не по дедлайну 0,1 с"
    assert _names(port) == OPEN_THEN_CLOSE
    _await(lambda: session.state == "closed", "state == closed")
    assert session.device_held is False
    assert rig.states == [("idle", "opening"), ("opening", "stopping"), ("stopping", "closed")]


@pytest.mark.timeout(20)
def test_дедлайн_старта(rig):
    port, session = rig.make(open_delay_s=0.5)
    started = time.perf_counter()
    result = session.start(0.1)
    seconds = time.perf_counter() - started

    assert result is False
    assert 0.08 <= seconds < 0.3  # ≈ 0,1 с: возврат по сроку, до `close`
    assert "close" not in _names(port)
    _await(lambda: session.state == "closed", "state == closed после отката", deadline=2.0)
    assert _names(port) == OPEN_THEN_CLOSE
    assert "start_grabbing" not in _names(port)


@pytest.mark.timeout(20)
def test_старт_пока_владелец_жив(rig):
    box: dict = {}

    def on_state(old: str, new: str) -> None:
        if new == "error" and "inside" not in box:
            box["inside"] = session.start(0.5)  # из потока владельца: сразу False

    port, session = rig.make(get_frame_errors=3, on_state=on_state)
    assert session.start(2.0) is True
    _await(lambda: "release" in _names(port), "владелец закрыл порт после 3 ошибок")
    assert box["inside"] is False
    assert _names(port).count("open") == 1  # второго open нет

    _await(lambda: session.device_held is False, "владелец вышел")
    before = _names(port)
    session.stop(1.0)
    assert session.state == "closed"
    assert _names(port) == before  # порт из `error` в `closed` не зовётся


@pytest.mark.timeout(20)
def test_старт_при_живом_владельце_в_error_из_другого_потока(rig):
    gate = threading.Event()
    box: dict = {}

    def on_state(old: str, new: str) -> None:
        if new == "error":
            gate.wait(2.0)  # владелец стоит в `error` и ещё не вышел

    port, session = rig.make(get_frame_errors=3, on_state=on_state)
    session.start(0.3)
    _await(lambda: session.state == "error", "state == error")
    assert session.device_held is True
    t = _in_thread(lambda: session.start(0.5), box, "x")
    t.join(2.0)
    assert box["x"][0] is False
    assert box["x"][1] < 0.1, "отказ по живому владельцу — сразу, без очереди"
    gate.set()
    _await(lambda: session.device_held is False, "владелец вышел")
    assert session.start(2.0) is True  # владелец вышел: новый цикл
    assert _names(port).count("open") == 2


@pytest.mark.timeout(20)
def test_второй_start_во_время_opening_ждёт_итога_и_не_открывает_второй_раз(rig):
    port, session = rig.make(open_delay_s=0.3)
    box: dict = {}
    first = _in_thread(lambda: session.start(3.0), box, "first")
    time.sleep(0.05)
    second = _in_thread(lambda: session.start(3.0), box, "second")
    first.join(5.0)
    second.join(5.0)
    assert box["first"][0] is True
    assert box["second"][0] is True
    assert _names(port).count("open") == 1


@pytest.mark.timeout(20)
def test_старт_joiner_по_своему_сроку_не_откатывает_чужой_цикл(rig):
    port, session = rig.make(open_delay_s=0.4)
    box: dict = {}
    first = _in_thread(lambda: session.start(3.0), box, "first")
    time.sleep(0.05)
    assert session.start(0.05) is False  # свой срок joiner'а
    first.join(5.0)
    assert box["first"][0] is True  # цикл создателя жив
    assert session.state == "grabbing"


@pytest.mark.timeout(20)
def test_grabbing_не_перезаписывает_stopping(rig):
    port, session = rig.make(open_delay_s=0.3)
    box: dict = {}
    a = _in_thread(lambda: session.start(3.0), box, "a")
    time.sleep(0.05)
    session.stop(2.0)
    a.join(5.0)
    assert ("opening", "grabbing") not in rig.states
    assert session.state == "closed"
    # compare-and-set напрямую: из `closed` переход «в grabbing» не проходит
    assert session._cas(("opening",), "grabbing") is False
    assert session.state == "closed"


@pytest.mark.timeout(20)
def test_внешний_stop_не_держит_замок_пока_ждёт_владельца(rig):
    port, session = rig.make(frame_period_s=10.0, timeout_ms=500)
    assert session.start(2.0) is True
    _await(lambda: "get_frame" in _names(port), "владелец в get_frame")
    box: dict = {}
    stopper = _in_thread(lambda: session.stop(2.0), box, "stop")
    _await(lambda: session.state == "stopping", "state == stopping", deadline=1.0)
    # Пока stop() ждёт владельца (~0,5 с): замок свободен — состояние читается, start() отвечает сразу.
    assert session._lock.acquire(timeout=0.05), "stop() держит замок состояния на join владельца"
    session._lock.release()
    assert session.start(1.0) is False
    stopper.join(3.0)
    assert not stopper.is_alive()
    _await(lambda: session.state == "closed", "state == closed")


@pytest.mark.timeout(20)
def test_исключение_из_on_frame_не_останавливает_захват(rig):
    def boom(frame) -> None:
        raise RuntimeError("on_frame сломан")

    port, session = rig.make(on_frame=boom)
    assert session.start(2.0) is True
    _await(lambda: len(rig.frames) >= 3, "3 вызова on_frame")
    assert session.state == "grabbing"
    assert session.errors == 0  # не ошибка порта
    session.stop(2.0)
    _await(lambda: session.state == "closed", "state == closed")
    assert _names(port).count("close") == 1


@pytest.mark.timeout(20)
def test_on_stall_из_потока_сторожа_и_потоки_daemon(rig):
    stall_threads: list[threading.Thread] = []
    port, session = rig.make(
        timeout_ms=100,
        watchdog_s=0.5,
        get_frame_hang_s=0.8,
        on_stall=lambda call, seconds: stall_threads.append(threading.current_thread()),
    )
    assert session.start(2.0) is True
    _await(lambda: len(stall_threads) >= 1, "on_stall", deadline=3.0)
    owner_ids = {c[2] for c in list(port.calls)}
    assert stall_threads[0].ident not in owner_ids  # колбэк — из потока сторожа, не владельца
    assert stall_threads[0].daemon is True
    owners = [t for t in threading.enumerate() if t.name == "camera_device-owner"]
    assert owners and all(t.daemon for t in owners)
    session.stop(2.0)
    _await(lambda: session.state == "closed", "state == closed")
