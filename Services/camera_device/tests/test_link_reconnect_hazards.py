# -*- coding: utf-8 -*-
"""Тесты опасности цикла попыток сеанса (W2-a, п.12 DESIGN): поток-владелец, правки в окнах, стоп, исключения.

Автор — исполнитель (teamlead). Порт — фейк (`make_link_event_port`), сеанс и `WorkerManager` — настоящие.
Вызов, который может зависнуть, идёт в daemon-потоке с дедлайном `join`; ожидание — опрос с дедлайном.
Ожидаемые значения — литералы.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from multiprocess_framework.modules.worker_module import WorkerManager
from Services.camera_device.params import Step
from Services.camera_device.session import DeviceSession
from Services.camera_device.testing import fake_port
from Services.camera_device.testing.fake_port import FAKE_BINDINGS

_WAIT_S = 6.0


def _call(fn: Callable[[], Any], deadline: float = 8.0) -> Any:
    """`fn` в daemon-потоке с дедлайном; исключение пробрасывается."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — исключение возвращается тесту
            box["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(deadline)
    assert not worker.is_alive(), f"вызов не вернулся за {deadline} с"
    if "error" in box:
        raise box["error"]
    return box.get("result")


def _await(pred: Callable[[], bool], message: str, deadline: float = _WAIT_S, seen: Callable[[], Any] = None) -> None:
    end = time.monotonic() + deadline
    while not pred():
        if time.monotonic() >= end:
            observed = f"; наблюдалось: {seen()!r}" if seen is not None else ""
            pytest.fail(f"не дождались за {deadline} с: {message}{observed}")
        time.sleep(0.005)


def _exposure(value: float) -> Step:
    return Step("exposure_time", FAKE_BINDINGS["exposure_time"], value)


def _plan(exposure: float = 1000.0) -> tuple[Step, ...]:
    return (Step("trigger_mode", FAKE_BINDINGS["trigger_mode"], "Off"), _exposure(exposure))


def _names(port: Any, name: str) -> list[int]:
    """Индексы вызовов `name` в журнале порта."""
    return [i for i, (n, _args, _tid) in enumerate(list(port.calls)) if n == name]


def _exposure_writes(port: Any, start: int, end: int | None = None) -> list[Any]:
    """Значения записей `ExposureTime` в журнале порта между индексами вызовов `start` и `end`."""
    calls = list(port.calls)[start:end]
    return [args[1] for n, args, _tid in calls if n == "set_param" and args[0] == "ExposureTime"]


class _Rig:
    def __init__(self) -> None:
        self.wm = WorkerManager("test_link_hazards")
        self.sessions: list[DeviceSession] = []
        self.states: list[str] = []
        self.frames: list[Any] = []

    def make(self, *, run: tuple = (), reconnect: bool = True, silence: float = 0.0, interval: float = 0.3, **opts):
        opts.setdefault("frame_period_s", 0.01)
        port = fake_port.make_link_event_port(**opts)
        session = DeviceSession(
            port,
            port.sdk,
            None,
            timeout_ms=100,
            watchdog_s=5.0,
            on_frame=self.frames.append,
            on_state=lambda old, new: self.states.append(new),
            workers=self.wm,
            worker_prefix=f"camera_device_lh_{len(self.sessions)}",
            run=run or _plan(),
            reconnect=reconnect,
            link_silence_s=silence,
            reconnect_interval_s=interval,
        )
        self.sessions.append(session)
        return port, session

    def grab(self, session: DeviceSession) -> None:
        assert _call(lambda: session.start(5.0)) is True
        _await(lambda: session.state == "grabbing" and len(self.frames) >= 2, "grabbing и кадры")

    def teardown(self) -> None:
        for session in self.sessions:
            stopper = threading.Thread(target=session.stop, args=(2.0,), daemon=True)
            stopper.start()
            stopper.join(5.0)
        self.wm.stop_all_workers(2.0)


@pytest.fixture
def rig():
    r = _Rig()
    yield r
    r.teardown()


@pytest.fixture
def logs():
    records: list[logging.LogRecord] = []

    class _Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger("camera_device.session")
    handler = _Collect(level=logging.DEBUG)
    old = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    yield records
    logger.removeHandler(handler)
    logger.setLevel(old)


def _lose_and_return(rig: _Rig, port: Any, session: DeviceSession, opens_before: int) -> None:
    """Событие `disconnected` -> `lost` -> новый `open` -> снова `grabbing` с кадрами."""
    lost_before = rig.states.count("lost")
    port.emit_link_event("disconnected")
    _await(lambda: rig.states.count("lost") == lost_before + 1, "переход в lost", seen=lambda: list(rig.states))
    _await(
        lambda: len(_names(port, "open")) > opens_before and session.state == "grabbing",
        "новый open и grabbing",
        seen=lambda: (len(_names(port, "open")), session.state),
    )


def test_one_owner_thread_across_reconnects(rig):
    """Три переподключения: `open` и `get_frame` — из одного потока, открытых дескрипторов не больше одного."""
    port, session = rig.make()
    rig.grab(session)
    for k in range(3):
        _lose_and_return(rig, port, session, opens_before=k + 1)

    assert len(_names(port, "open")) == 4
    threads = {tid for n, _args, tid in list(port.calls) if n in ("open", "get_frame")}
    assert len(threads) == 1, threads
    assert port.max_open_handles == 1
    assert session.link()["outages"] == 3


def test_write_accepted_before_drain_then_loss_reaches_device(rig):
    """Правка принята в `grabbing`, `_drain` не успел (потеря раньше): после второго `open` — новое значение."""
    port, session = rig.make()
    rig.grab(session)
    gate, entered, release = threading.Event(), threading.Event(), threading.Event()
    original = port.get_frame

    def held_get_frame(timeout_ms: int) -> Any:
        if gate.is_set():
            gate.clear()
            entered.set()
            release.wait(3.0)
        return original(timeout_ms)

    port.get_frame = held_get_frame
    gate.set()
    assert entered.wait(3.0), "владелец не вошёл в get_frame"
    first_open = _names(port, "open")[0]
    session.apply([_exposure(4321.0)], "restart")  # ящик опрашивается только после возврата get_frame
    port.emit_link_event("disconnected")
    release.set()

    _await(lambda: len(_names(port, "open")) >= 2, "второй open", seen=lambda: list(rig.states))
    second_open = _names(port, "open")[1]
    assert 4321.0 not in _exposure_writes(port, first_open, second_open), "_drain успел до потери"
    _await(lambda: 4321.0 in _exposure_writes(port, second_open), "правка записана после второго open")


def test_write_applied_before_loss_survives_reopen(rig):
    """Правка исполнена (`params` показывает её), затем потеря: переоткрытие пишет новое значение, не старое плана."""
    port, session = rig.make()
    rig.grab(session)
    session.apply([_exposure(2468.0)], "live")
    _await(
        lambda: session.params.get("exposure_time") == 2468.0, "params показывает правку", seen=lambda: session.params
    )

    port.emit_link_event("disconnected")
    _await(lambda: len(_names(port, "open")) >= 2, "второй open")
    second_open = _names(port, "open")[1]
    _await(lambda: _exposure_writes(port, second_open) != [], "запись экспозиции после второго open")
    time.sleep(0.3)
    assert _exposure_writes(port, second_open) == [2468.0]


def test_stale_link_event_discarded_before_regrab(rig):
    """Перезахват по правке без `restart_regrab`: событие, пришедшее при `close` перезахвата, не даёт `lost`."""
    port, session = rig.make(capabilities=fake_port.ALL_CAPABILITIES - {"restart_regrab"})
    rig.grab(session)
    original_close = port.close

    def noisy_close() -> None:
        port.emit_link_event("disconnected")  # SDK сообщает о закрытом нами сеансе прибора
        original_close()

    port.close = noisy_close
    session.apply([_exposure(1357.0)], "restart")
    _await(lambda: len(_names(port, "open")) >= 2, "перезахват: второй open")
    port.close = original_close
    time.sleep(0.5)

    assert "lost" not in rig.states, rig.states
    assert session.state == "grabbing"
    assert session.link()["outages"] == 0
    assert len(_names(port, "open")) == 2


def test_stop_during_retry_open_no_start_grabbing(rig):
    """Стоп во время `open` повтора (1 с): после стопа прибор не держится и `start_grabbing` не зовётся."""
    port, session = rig.make(open_delay_s=1.0)
    rig.grab(session)
    entered = threading.Event()
    original_open = port.open

    def watched_open(ident: Any) -> None:
        entered.set()
        original_open(ident)

    port.open = watched_open
    port.emit_link_event("disconnected")
    assert entered.wait(5.0), "повтор open не начался"
    _await(lambda: len(_names(port, "open")) >= 2, "повтор open в журнале")  # запись идёт внутри open после `entered`
    retry_open = _names(port, "open")[1]

    _call(lambda: session.stop(3.0))

    assert session.device_held is False
    assert session.state == "closed"
    assert "start_grabbing" not in [n for n, _a, _t in list(port.calls)[retry_open:]]
    opens = len(_names(port, "open"))
    time.sleep(1.0)
    assert len(_names(port, "open")) == opens


def test_non_port_error_retried_and_logged_once(rig, logs):
    """`OSError` в `open` повторов: цикл не падает, `lost` держится, ERROR со стеком — одна; затем возврат."""
    port, session = rig.make()
    rig.grab(session)
    original_open = port.open
    broken = threading.Event()
    broken.set()

    def failing_open(ident: Any) -> None:
        if broken.is_set():
            raise OSError("ctypes: access violation")
        original_open(ident)

    port.open = failing_open
    port.emit_link_event("disconnected")
    _await(lambda: session.link()["attempts"] >= 3, "три повтора", seen=lambda: session.link())

    assert session.state == "lost"
    assert "OSError" in (session.last_error or "")
    stacked = [r for r in list(logs) if r.levelno == logging.ERROR and r.exc_info]
    assert len(stacked) == 1, [r.getMessage() for r in stacked]
    assert isinstance(stacked[0].exc_info[1], OSError)

    broken.clear()
    _await(lambda: session.state == "grabbing", "возврат после исправления open", seen=lambda: session.state)


def test_apply_during_retry_start_grabbing_reaches_device(rig):
    """Правка приходит, пока повтор зовёт `start_grabbing` (после снимка плана) — доходит до прибора."""
    port, session = rig.make()
    rig.grab(session)
    original_start = port.start_grabbing
    starts = {"n": 0}

    def start_with_edit() -> None:
        starts["n"] += 1
        if starts["n"] == 1:
            session.apply([_exposure(9753.0)], "restart")  # переподключение: правка в план, снимок уже записан
        original_start()

    port.start_grabbing = start_with_edit
    port.emit_link_event("disconnected")
    _await(lambda: len(_names(port, "open")) >= 2, "второй open")
    second_open = _names(port, "open")[1]
    _await(
        lambda: 9753.0 in _exposure_writes(port, second_open),
        "правка записана после start_grabbing повтора",
        seen=lambda: _exposure_writes(port, second_open),
    )
    assert starts["n"] >= 1


def test_apply_while_awaiting_first_frame_reaches_device(rig):
    """Свободный поток после потери ждёт первого кадра (`lost`, `reconnecting`); правка в этом окне доходит."""
    port, session = rig.make(silence=1.0)
    rig.grab(session)
    original_get_frame = port.get_frame
    hush = threading.Event()

    def quiet_get_frame(timeout_ms: int) -> Any:
        if hush.is_set():
            time.sleep(timeout_ms / 1000.0)
            return None
        return original_get_frame(timeout_ms)

    original_start = port.start_grabbing
    started = threading.Event()

    def start_then_hush() -> None:
        original_start()
        if not started.is_set():  # только повтор; перезахват правкой потом кадры не глушит
            hush.set()  # кадров нет: повтор остаётся в окне ожидания первого кадра
            started.set()

    port.get_frame = quiet_get_frame
    port.start_grabbing = start_then_hush
    port.emit_link_event("disconnected")
    assert started.wait(5.0), "повтор не дошёл до start_grabbing"
    time.sleep(0.2)
    assert session.state == "lost" and session.reconnecting is True
    second_open = _names(port, "open")[1]
    session.apply([_exposure(8642.0)], "restart")
    hush.clear()

    _await(lambda: session.state == "grabbing", "первый кадр -> grabbing", seen=lambda: session.state)
    _await(
        lambda: 8642.0 in _exposure_writes(port, second_open),
        "правка из окна ожидания записана",
        seen=lambda: _exposure_writes(port, second_open),
    )


def test_regrab_by_apply_is_not_loss(rig):
    """Перезахват по правке (`open` 1 с, без `restart_regrab`/`live_write`) при тишине 0,5 с — не потеря связи."""
    port, session = rig.make(
        silence=0.5,
        open_delay_s=1.0,
        frame_period_s=0.3,  # первый кадр после start_grabbing — через 0,3 с: get_frame сначала даёт None
        capabilities=fake_port.ALL_CAPABILITIES - {"restart_regrab", "live_write"},
    )
    rig.grab(session)
    session.apply([_exposure(1111.0)], "live")
    _await(lambda: len(_names(port, "open")) >= 2, "перезахват: второй open")
    time.sleep(1.5)

    assert "lost" not in rig.states, rig.states
    assert session.state == "grabbing"
    assert len(_names(port, "open")) == 2


# ---------------------------------------------------------------------------------------------- #
# Ревью стадии 5 (находки 1, 3, 8)
# ---------------------------------------------------------------------------------------------- #


def test_apply_in_first_refusal_window_reaches_device(rig):
    """Находка 1: правка из `on_state(busy)` отказа первой попытки (окно до `reconnecting`) доходит до прибора."""
    port = fake_port.make_link_event_port(frame_period_s=0.01, busy_for_s=0.8)
    holder: dict[str, Any] = {}

    def on_state(old: str, new: str) -> None:
        rig.states.append(new)
        if new == "busy" and "edited" not in holder:
            holder["edited"] = True
            holder["session"].apply([_exposure(2222.0)], "restart")

    session = DeviceSession(
        port,
        port.sdk,
        None,
        timeout_ms=100,
        watchdog_s=5.0,
        on_frame=rig.frames.append,
        on_state=on_state,
        workers=rig.wm,
        worker_prefix="camera_device_lh_window",
        run=_plan(1000.0),
        reconnect=True,
        reconnect_interval_s=0.3,
    )
    rig.sessions.append(session)
    holder["session"] = session

    assert _call(lambda: session.start(5.0)) is False
    _await(lambda: session.state == "grabbing", "grabbing после освобождения", seen=lambda: session.state)
    assert holder.get("edited") is True
    assert _exposure_writes(port, 0) == [2222.0]


def test_terminal_error_marks_link_lost(rig):
    """Находка 3: без `reconnect` три ошибки кадра -> `error`, и `link.state` — `lost`, не `up`."""
    port, session = rig.make(reconnect=False, get_frame_errors=3)
    _call(lambda: session.start(5.0))
    _await(lambda: session.state == "error", "error после трёх ошибок кадра", seen=lambda: session.state)

    assert session.link()["state"] == "lost"


def test_reopen_without_first_frame_retries_when_silence_off(rig):
    """Находка 8: `link_silence_s 0`, свободный поток, после переоткрытия кадров нет — повтор через 3 с, а не вечно."""
    port, session = rig.make(silence=0.0)
    rig.grab(session)
    original_get_frame = port.get_frame
    original_start = port.start_grabbing
    hush = threading.Event()

    def quiet_get_frame(timeout_ms: int) -> Any:
        if hush.is_set():
            time.sleep(timeout_ms / 1000.0)
            return None
        return original_get_frame(timeout_ms)

    def start_then_hush() -> None:
        original_start()
        hush.set()  # после каждого переоткрытия кадров нет

    port.get_frame = quiet_get_frame
    port.start_grabbing = start_then_hush
    port.emit_link_event("disconnected")

    _await(
        lambda: session.link()["attempts"] >= 2,
        "второй повтор после 3 с без первого кадра",
        6.0,
        seen=lambda: session.link(),
    )
    assert session.state == "lost"
    assert session.link()["outages"] == 1
