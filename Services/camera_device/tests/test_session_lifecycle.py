# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты сеанса `DeviceSession` (Task 2.1, RED до кода; автор — тестер).

Источник — блоки DESIGN и ACCEPTANCE `plans/2026-10-18_camera-device-service/tasks/2.1.md`.
Ожидаемые значения — литералы из ACCEPTANCE, не вычисляются из кода под тестом.
Любой вызов, который может зависнуть (`start`/`stop`), идёт в daemon-потоке с дедлайном `join`;
в teardown фикстуры `rig` всегда `stop()` и `join` потоков, порождённых сеансом.

Импорт `DeviceSession` — внутри `_session_cls()`: пока `session.py` нет, тест ПАДАЕТ, а не ломает сборку.
Пункт ACCEPTANCE «`close` ровно 1 на каждый удавшийся `open`» проверяется внутри каждого теста.
"""

from __future__ import annotations

import threading
import time

import pytest

from Services.camera_device.interface import DeviceIdentity
from multiprocess_framework.modules.worker_module import WorkerManager
from Services.camera_device.testing.fake_port import make_port

# Журнал одного цикла `start -> кадры -> stop` без повторов `get_frame` (литерал ACCEPTANCE).
CYCLE = ["acquire", "enum_devices", "open", "start_grabbing", "get_frame", "stop_grabbing", "close", "release"]


def _session_cls():
    from Services.camera_device.session import DeviceSession

    return DeviceSession


def _names(port) -> list[str]:
    return [call[0] for call in list(port.calls)]


def _compact(names: list[str]) -> list[str]:
    """Свернуть подряд идущие `get_frame` в один (число кадров не фиксировано)."""
    out: list[str] = []
    for name in names:
        if name == "get_frame" and out and out[-1] == "get_frame":
            continue
        out.append(name)
    return out


def _await(pred, message: str, deadline: float = 2.0) -> None:
    """Опрос с дедлайном вместо `sleep`: `closed` и прочие итоги приходят из потока владельца."""
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if pred():
            return
        time.sleep(0.005)
    assert pred(), f"не дождались за {deadline} с: {message}"


def _call(fn, deadline: float = 4.0):
    """Вызвать `fn` в daemon-потоке; вернуть (результат, секунды). Не вернулся за `deadline` — тест падает."""
    box: dict = {}

    def run() -> None:
        t0 = time.perf_counter()
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — исключение возвращается вызывающему тесту
            box["error"] = exc
        box["seconds"] = time.perf_counter() - t0

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(deadline)
    assert not worker.is_alive(), f"вызов не вернулся за {deadline} с"
    if "error" in box:
        raise box["error"]
    return box["result"], box["seconds"]


class _Rig:
    """Сеансы и фейковые порты теста: собирает кадры и зависания, в teardown гасит всё."""

    def __init__(self) -> None:
        self._before = set(threading.enumerate())
        self.wm = WorkerManager("test_cam")  # потоки сеанса — воркеры настоящего менеджера
        self.sessions: list = []
        self.port = None
        self.frames: list = []
        self.frame_threads: list = []
        self.stalls: list[tuple[str, float]] = []

    def make(self, *, ident=None, timeout_ms: int = 500, watchdog_s: float = 5.0, on_frame=None, **port_opts):
        port_opts.setdefault("frame_period_s", 0.01)  # без периода цикл горячий и раздувает журнал
        self.port = make_port(**port_opts)

        def frame_cb(frame) -> None:
            self.frames.append(frame)
            self.frame_threads.append(threading.current_thread())
            if on_frame is not None:
                on_frame(frame)

        session = _session_cls()(
            self.port,
            self.port.sdk,
            ident,
            timeout_ms=timeout_ms,
            watchdog_s=watchdog_s,
            on_frame=frame_cb,
            workers=self.wm,
            worker_prefix=f"camera_device_{len(self.sessions)}",
            on_stall=lambda call, seconds: self.stalls.append((call, seconds)),
        )
        self.sessions.append(session)
        return session

    def new_port_session(self, **kwargs):
        """Ещё один сеанс на новом порте (несколько сценариев в одном тесте); счётчики кадров обнуляются."""
        self.frames = []
        self.frame_threads = []
        self.stalls = []
        return self.make(**kwargs)

    def teardown(self) -> None:
        for session in self.sessions:
            try:
                _call(lambda s=session: s.stop(2.0), 5.0)
            except BaseException:  # noqa: BLE001 — teardown не маскирует падение теста
                pass
        me = threading.current_thread()
        for thread in threading.enumerate():
            if thread not in self._before and thread is not me and thread.daemon:
                thread.join(3.0)  # владелец и сторож — daemon; зависание фейка (≤ 1,5 с) кончается само
        self.wm.stop_all_workers(2.0)


@pytest.fixture
def rig():
    r = _Rig()
    yield r
    r.teardown()


def _wait_closed(session) -> None:
    _await(lambda: session.state == "closed", "state == closed")


def _finish(rig, session) -> None:
    """stop + ожидание `closed` + «close ровно 1 на каждый удавшийся open»."""
    _call(lambda: session.stop(2.0))
    _wait_closed(session)
    names = _names(rig.port)
    assert names.count("close") == names.count("open") == 1


# ---------------------------------------------------------------------------------------------
# ACCEPTANCE


@pytest.mark.timeout(20)
def test_журнал_старт_стоп(rig):
    session = rig.make()
    assert _call(lambda: session.start(2.0))[0] is True
    assert session.device_held is True
    _await(lambda: len(rig.frames) >= 3, "3 кадра")
    _call(lambda: session.stop(2.0))
    _wait_closed(session)

    names = _names(rig.port)
    assert _compact(names) == CYCLE
    assert names.count("open") == 1
    assert names.count("close") == 1
    assert session.device_held is False


@pytest.mark.timeout(20)
def test_один_поток_владелец(rig):
    session = rig.make()
    assert _call(lambda: session.start(2.0))[0] is True
    _await(lambda: len(rig.frames) >= 3, "3 кадра")
    _call(lambda: session.stop(2.0))
    _wait_closed(session)

    names = _names(rig.port)
    assert {"acquire", "enum_devices", "release"} <= set(names)  # записи фейкового DeviceSdk тоже в журнале
    thread_ids = {call[2] for call in list(rig.port.calls)}
    assert len(thread_ids) == 1
    assert threading.get_ident() not in thread_ids
    # `on_frame` зовётся из того же потока владельца
    assert {t.ident for t in rig.frame_threads} == thread_ids
    assert names.count("close") == names.count("open") == 1


@pytest.mark.timeout(20)
def test_стоп_ждёт_таймаут_кадра(rig):
    session = rig.make(frame_period_s=10.0, timeout_ms=500)
    assert _call(lambda: session.start(2.0))[0] is True
    _await(lambda: "get_frame" in _names(rig.port), "владелец вошёл в get_frame")

    _, seconds = _call(lambda: session.stop(0.2))
    # Предел 0,2 + 0,5 = 0,7 с (срок ожидания + timeout_ms); +0,1 с допуск на планировщик потоков -> 0,8 (ACCEPTANCE).
    assert seconds <= 0.8
    _wait_closed(session)  # `closed` — только после выхода владельца; опрос с дедлайном 2 с
    names = _names(rig.port)
    assert names[-3:] == ["stop_grabbing", "close", "release"]
    assert names.count("close") == names.count("open") == 1


@pytest.mark.timeout(20)
def test_старт_во_время_stopping(rig):
    session = rig.make(frame_period_s=10.0, timeout_ms=500)
    assert _call(lambda: session.start(2.0))[0] is True
    _await(lambda: "get_frame" in _names(rig.port), "владелец вошёл в get_frame")

    stopper = threading.Thread(target=lambda: session.stop(2.0), daemon=True)
    stopper.start()
    # stop() переводит state в stopping синхронно, в потоке вызывающего; окно держится ≥ ~0,4 с (хвост get_frame 500 мс)
    _await(lambda: session.state == "stopping", "state == stopping", deadline=1.0)

    result, seconds = _call(lambda: session.start(2.0))
    assert result is False
    # Граница 0,1 с из ACCEPTANCE: отказ по состоянию, а не по дедлайну `start(2.0)` и не по окончанию окна stopping.
    assert seconds < 0.1
    assert _names(rig.port).count("open") == 1  # второго open нет

    stopper.join(3.0)
    assert not stopper.is_alive()
    _wait_closed(session)
    names = _names(rig.port)
    assert names.count("open") == 1
    assert names.count("close") == 1


@pytest.mark.timeout(20)
def test_стоп_из_on_frame(rig):
    box: dict = {}
    returned = threading.Event()

    def on_frame(frame) -> None:
        if box.get("done"):
            return
        box["done"] = True
        try:
            box["session"].stop()
        except BaseException as exc:  # noqa: BLE001 — исключения из on_frame сеанс глотает, фиксируем сами
            box["error"] = exc
        returned.set()

    session = rig.make(on_frame=on_frame)
    box["session"] = session
    # Результат `start` не проверяем: стоп из первого кадра может опередить ответ владельца. Главное — не зависнуть.
    _call(lambda: session.start(2.0))

    assert returned.wait(2.0), "stop() из on_frame не вернулся за 2 с"
    assert "error" not in box
    _wait_closed(session)
    names = _names(rig.port)
    assert names[-3:] == ["stop_grabbing", "close", "release"]
    assert names.count("stop_grabbing") == 1
    assert names.count("close") == names.count("open") == 1


@pytest.mark.timeout(20)
def test_busy(rig):
    session = rig.make(busy_for_s=60.0)  # `open` в течение 60 с после создания фейка -> PortError(kind="busy")

    assert _call(lambda: session.start(2.0))[0] is False
    assert session.state == "busy"
    _await(lambda: "release" in _names(rig.port), "release после отказа open")
    names = _names(rig.port)
    assert names == ["acquire", "enum_devices", "open", "release"]
    assert names.count("close") == 0  # open не удался -> close не зовётся


@pytest.mark.timeout(20)
def test_сторож_один_раз(rig):
    session = rig.make(timeout_ms=100, watchdog_s=0.5, get_frame_hang_s=1.5)
    _call(lambda: session.start(2.0))

    _await(lambda: len(rig.stalls) >= 1, "первый on_stall", deadline=3.0)
    # Зависший вызов кончается в 1,5 с: после него в журнале появляется следующий get_frame.
    hung_calls = _names(rig.port).count("get_frame")
    _await(lambda: _names(rig.port).count("get_frame") > hung_calls, "get_frame после зависания", deadline=3.0)
    time.sleep(0.3)  # запас: лишний on_stall, будь он, пришёл бы за ближайшие тики сторожа
    assert len(rig.stalls) == 1
    assert rig.stalls[0][0] == "get_frame"
    assert rig.stalls[0][1] >= 0.5

    rig.port.arm_hang(1.5)  # второе зависание
    _await(lambda: len(rig.stalls) >= 2, "второй on_stall", deadline=3.0)
    hung_calls = _names(rig.port).count("get_frame")
    _await(lambda: _names(rig.port).count("get_frame") > hung_calls, "get_frame после второго зависания", deadline=3.0)
    time.sleep(0.3)
    assert len(rig.stalls) == 2  # по одному на зависание
    assert rig.stalls[1][0] == "get_frame"
    assert rig.stalls[1][1] >= 0.5

    _finish(rig, session)


@pytest.mark.timeout(30)
def test_три_ошибки_подряд(rig):
    # A: 3 ошибки подряд -> error; затем stop_grabbing, close, release
    session = rig.make(get_frame_errors=3)
    _call(lambda: session.start(2.0))
    _await(lambda: "release" in _names(rig.port), "сеанс закрыл порт после 3 ошибок")
    names = _names(rig.port)
    assert session.state == "error"
    assert session.errors == 3
    assert names[-4:] == ["get_frame", "stop_grabbing", "close", "release"]
    assert names.count("get_frame") == 3
    assert names.count("close") == names.count("open") == 1
    assert "PortError" in session.last_error and "other" in session.last_error
    _call(lambda: session.stop(2.0))  # из error -> closed, порт не зовётся
    _wait_closed(session)
    assert _names(rig.port) == names

    # B: 2 ошибки, затем кадр -> grabbing
    session = rig.new_port_session(get_frame_errors=2)
    _call(lambda: session.start(2.0))
    _await(lambda: len(rig.frames) >= 1, "кадр после 2 ошибок")
    assert session.state == "grabbing"
    assert session.errors == 2
    assert _names(rig.port).count("close") == 0
    _finish(rig, session)

    # C: err/none чередуются — `None` сбрасывает счётчик подряд идущих ошибок -> grabbing, errors == 3
    session = rig.new_port_session(get_frame_script=("err", "none", "err", "none", "err"))
    _call(lambda: session.start(2.0))
    _await(lambda: len(rig.frames) >= 1, "кадр после сценария")
    assert session.state == "grabbing"
    assert session.errors == 3
    assert _names(rig.port).count("close") == 0
    _finish(rig, session)


@pytest.mark.timeout(20)
def test_not_found(rig):
    session = rig.make(ident=DeviceIdentity("serial", "NOPE"))

    assert _call(lambda: session.start(2.0))[0] is False
    assert session.state == "not_found"
    _await(lambda: "release" in _names(rig.port), "release после not_found")
    names = _names(rig.port)
    assert names == ["acquire", "enum_devices", "release"]  # open не зовётся -> close тоже нет
    assert names.count("open") == names.count("close") == 0


@pytest.mark.timeout(30)
def test_второй_цикл(rig):
    session = rig.make()

    assert _call(lambda: session.start(2.0))[0] is True
    _await(lambda: len(rig.frames) >= 3, "3 кадра в первом цикле")
    _call(lambda: session.stop(2.0))
    _wait_closed(session)
    first_cycle_frames = len(rig.frames)

    assert _call(lambda: session.start(2.0))[0] is True
    _await(lambda: len(rig.frames) >= first_cycle_frames + 3, "3 кадра во втором цикле")
    _call(lambda: session.stop(2.0))
    _wait_closed(session)

    calls = list(rig.port.calls)
    names = [c[0] for c in calls]
    assert _compact(names) == CYCLE + CYCLE
    assert names.count("open") == names.count("close") == 2

    split = names.index("acquire", 1)  # второй цикл начинается со второго acquire
    first_ids = {c[2] for c in calls[:split]}
    second_ids = {c[2] for c in calls[split:]}
    assert len(first_ids) == 1 and len(second_ids) == 1  # в каждом цикле — один владелец
    assert threading.get_ident() not in first_ids | second_ids
    # «id потока владельца в циклах различаются»: `threading.get_ident()` освобождённого потока ОС вправе
    # выдать повторно, поэтому различие проверяем по объектам Thread, пойманным в `on_frame` каждого цикла.
    first_owner = rig.frame_threads[0]
    second_owner = rig.frame_threads[first_cycle_frames]
    assert first_owner is not second_owner
