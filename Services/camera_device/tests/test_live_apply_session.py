# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты живой правки и ящика владельца (Task 2.4a, RED до кода; автор — тестер).

Источник — блоки DESIGN и ACCEPTANCE `plans/2026-10-18_camera-device-service/tasks/2.4a.md`.
Ожидаемые значения — литералы из ACCEPTANCE, не вычисляются из кода под тестом.
Интерфейс из DESIGN: `session.apply(steps, policy)` (не блокирует), `session.call(fn, timeout) -> (ok, результат)`,
счётчики фейка `port.open_handles` / `port.max_open_handles`.
Шаги строит `params.build_plan` по `CameraDeviceRegisters` и `FAKE_BINDINGS`. Журнал порта сравнивается после
фильтра `_KEPT` (отбрасываются `acquire`, `enum_devices`, `describe_param`, `release`, `get_frame`); записи
свёрнуты в строки `set_param(Узел,значение)`, `get_param(Узел)`.
Любой вызов, который может зависнуть (`start`/`stop`/`apply`/`call`), идёт в daemon-потоке с дедлайном `join`;
в teardown фикстуры `rig` всегда `stop()`. Все сеансы собраны из настоящих `DeviceSession` + `WorkerManager`
+ фейк-порта. Фейк `arm_hang` взводит ОДНО зависание следующего `get_frame`; момент начала зависания виден по
сбросу `port._hang_s` в 0 (приватное поле фейка из `testing/`, одного пакета с тестом).
"""

from __future__ import annotations

import threading
import time

import pytest

from Services.camera_device.params import Step, build_plan
from Services.camera_device.registers_base import CameraDeviceRegisters
from Services.camera_device.session import DeviceSession
from Services.camera_device.testing.fake_port import ALL_CAPABILITIES, FAKE_BINDINGS, make_port
from multiprocess_framework.modules.worker_module import WorkerManager

_KEPT = {"open", "set_param", "get_param", "start_grabbing", "stop_grabbing", "close"}
NO_RESTART_REGRAB = ALL_CAPABILITIES - {"restart_regrab"}


def _step(field: str, **overrides) -> Step:
    """Шаг поля из плана конфига `trigger_managed: true, trigger_mode: On, trigger_source: SelfTrigger`."""
    values = CameraDeviceRegisters(
        trigger_managed=True, trigger_mode="On", trigger_source="SelfTrigger", **overrides
    ).model_dump()
    return next(s for s in build_plan(CameraDeviceRegisters, values, FAKE_BINDINGS) if s.field == field)


def _run_plan(period: int = 40) -> list[Step]:
    values = CameraDeviceRegisters(
        trigger_managed=True, trigger_mode="On", trigger_source="SelfTrigger", trigger_period_ms=period
    ).model_dump()
    return build_plan(CameraDeviceRegisters, values, FAKE_BINDINGS)


def _names(port) -> list[str]:
    out: list[str] = []
    for name, args, _tid in list(port.calls):
        if name not in _KEPT:
            continue
        if name in ("set_param", "get_param"):
            out.append(f"{name}({args[0]},{args[1]})" if name == "set_param" else f"get_param({args[0]})")
        else:
            out.append(name)
    return out


def _count(port, name: str) -> int:
    return sum(1 for call in list(port.calls) if call[0] == name)


def _await(pred, message: str, deadline: float = 3.0) -> None:
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if pred():
            return
        time.sleep(0.005)
    assert pred(), f"не дождались за {deadline} с: {message}"


def _call(fn, deadline: float = 4.0):
    """Вызвать `fn` в daemon-потоке; не вернулся за `deadline` — тест падает."""
    box: dict = {}

    def run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — исключение возвращается вызывающему тесту
            box["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(deadline)
    assert not worker.is_alive(), f"вызов не вернулся за {deadline} с"
    if "error" in box:
        raise box["error"]
    return box.get("result")


class _Rig:
    def __init__(self) -> None:
        self.sessions: list[DeviceSession] = []
        self.port = None
        self.events: list[tuple[str, str]] = []
        self.wm = WorkerManager("test_cam_live")

    def make(self, *, run=(), **port_opts) -> DeviceSession:
        port_opts.setdefault("frame_period_s", 0.01)
        self.port = make_port(**port_opts)
        session = DeviceSession(
            self.port,
            self.port.sdk,
            None,
            timeout_ms=500,
            watchdog_s=5.0,
            on_frame=lambda frame: None,
            on_state=lambda old, new: self.events.append((old, new)),
            workers=self.wm,
            worker_prefix=f"camera_device_live_{len(self.sessions)}",
            run=tuple(run),
        )
        self.sessions.append(session)
        return session

    def start(self, session: DeviceSession) -> bool:
        return _call(lambda: session.start(5.0))

    def stop_and_wait(self, session: DeviceSession) -> None:
        _call(lambda: session.stop(2.0))
        _await(lambda: session.state == "closed", "state == closed после stop")


@pytest.fixture
def rig():
    r = _Rig()
    yield r
    for session in r.sessions:
        try:
            _call(lambda s=session: s.stop(2.0))
        except Exception:  # noqa: BLE001 — teardown не маскирует падение теста
            pass
    r.wm.stop_all_workers(2.0)


def _wait_regrab_done(session, port, field: str, value, starts: int) -> None:
    """Перезахват завершён: значение поля подтверждено, последняя запись журнала — `start_grabbing`."""
    _await(
        lambda: (
            session.params.get(field) == value
            and _names(port)[-1:] == ["start_grabbing"]
            and _names(port).count("start_grabbing") >= starts
        ),
        f"перезахват {field}={value}",
    )


# -- строка 1: restart с restart_regrab ----------------------------------------------------------


def test_restart_с_restart_regrab_пишет_в_открытый_порт_без_open_close(rig):
    session = rig.make(run=_run_plan(40))
    assert rig.start(session) is True
    _call(lambda: session.apply([_step("trigger_period_ms", trigger_period_ms=60)], "restart"))
    _wait_regrab_done(session, rig.port, "trigger_period_ms", 60, starts=2)
    names = _names(rig.port)
    first_start = names.index("start_grabbing")
    i_stop = names.index("stop_grabbing", first_start)
    i_start = names.index("start_grabbing", i_stop)
    assert names[i_stop + 1 : i_start] == [
        "set_param(TriggerSelfTriggerPeriod,60)",
        "get_param(TriggerSelfTriggerPeriod)",
    ]
    assert "open" not in names[first_start:]
    assert "close" not in names[first_start:]
    assert session.params["trigger_period_ms"] == 60
    assert "trigger_period_ms" not in session.param_errors


# -- строка 1 (без restart_regrab) + строка «окно перезахвата» -----------------------------------


def test_restart_без_restart_regrab_переоткрывает_порт_state_остаётся_grabbing(rig):
    session = rig.make(run=_run_plan(40), capabilities=NO_RESTART_REGRAB, open_delay_s=0.3)
    assert rig.start(session) is True
    assert rig.events == [("idle", "opening"), ("opening", "grabbing")]
    _call(lambda: session.apply([_step("trigger_period_ms", trigger_period_ms=60)], "restart"))
    # окно перезахвата: в журнале после stop_grabbing уже есть close, нового start_grabbing ещё нет
    window: list[tuple[str, bool, list]] = []
    deadline = time.monotonic() + 4.0
    while time.monotonic() < deadline:
        state, held, events = session.state, session.device_held, list(rig.events)
        names = _names(rig.port)
        if names.count("start_grabbing") >= 2:
            break
        if "stop_grabbing" in names and "close" in names[names.index("stop_grabbing") :]:
            window.append((state, held, events))
        time.sleep(0.005)
    assert window, "окно перезахвата (close есть, второго start_grabbing нет) не наблюдалось"
    assert all(state == "grabbing" for state, _, _ in window)
    assert all(held is True for _, held, _ in window)
    assert all(events == [("idle", "opening"), ("opening", "grabbing")] for _, _, events in window)
    _wait_regrab_done(session, rig.port, "trigger_period_ms", 60, starts=2)
    names = _names(rig.port)
    i_stop = names.index("stop_grabbing")
    i_start = names.index("start_grabbing", i_stop)
    assert names[i_stop : i_start + 1] == [
        "stop_grabbing",
        "close",
        "open",
        "set_param(TriggerMode,On)",
        "get_param(TriggerMode)",
        "set_param(TriggerSource,SelfTrigger)",
        "get_param(TriggerSource)",
        "set_param(TriggerSelfTriggerPeriod,60)",
        "get_param(TriggerSelfTriggerPeriod)",
        "set_param(ExposureTime,10000.0)",
        "get_param(ExposureTime)",
        "start_grabbing",
    ]
    assert rig.events == [("idle", "opening"), ("opening", "grabbing")]  # ни одного нового значения состояния
    assert session.params["trigger_period_ms"] == 60
    assert "trigger_period_ms" not in session.param_errors


# -- строка 2: live при live_write ---------------------------------------------------------------


def test_live_при_live_write_пишет_без_остановки(rig):
    session = rig.make(run=_run_plan(40))
    assert rig.start(session) is True
    _call(lambda: session.apply([_step("exposure_time", exposure_time=1200.0)], "live"))
    _await(lambda: session.params.get("exposure_time") == 1200.0, "exposure_time == 1200.0")
    names = _names(rig.port)
    after = names[names.index("start_grabbing") + 1 :]
    assert after == ["set_param(ExposureTime,1200.0)", "get_param(ExposureTime)"]
    assert "stop_grabbing" not in names
    assert session.params["exposure_time"] == 1200.0
    assert session.state == "grabbing"


# -- строка 3 и строка «потоки»: два потока, один handle, порт только из владельца ----------------


def test_два_потока_apply_один_handle_последнее_значение_и_порт_только_из_владельца(rig):
    session = rig.make(run=_run_plan(40), capabilities=NO_RESTART_REGRAB, open_delay_s=0.2)
    assert rig.start(session) is True
    first_done = threading.Event()
    caller_ids: list[int] = []
    errors: list[BaseException] = []

    def caller(value: int, wait_for: threading.Event | None, signal: threading.Event | None) -> None:
        if wait_for is not None:
            wait_for.wait(2.0)
        caller_ids.append(threading.get_ident())
        try:
            session.apply([_step("trigger_period_ms", trigger_period_ms=value)], "restart")
        except BaseException as exc:  # noqa: BLE001 — отказ apply виден тесту, а не только предупреждению потока
            errors.append(exc)
        finally:
            if signal is not None:
                signal.set()

    threads = [
        threading.Thread(target=caller, args=(61, None, first_done), daemon=True),
        threading.Thread(target=caller, args=(62, first_done, None), daemon=True),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(4.0)
        assert not t.is_alive(), "apply не вернулся: должен не блокировать"
    assert errors == []
    _wait_regrab_done(session, rig.port, "trigger_period_ms", 62, starts=2)
    assert rig.port.max_open_handles == 1
    assert session.params["trigger_period_ms"] == 62
    journal_threads = {tid for _name, _args, tid in list(rig.port.calls)}
    assert len(journal_threads) == 1  # весь журнал порта (и SDK) — из одного потока, владельца
    assert journal_threads.isdisjoint(caller_ids)
    assert threading.get_ident() not in journal_threads


# -- строка 4: слияние правок за зависшим get_frame ----------------------------------------------


def test_слияние_двух_правок_за_зависанием_один_stop_grabbing(rig):
    session = rig.make(run=_run_plan(40))
    assert rig.start(session) is True
    rig.port.arm_hang(0.3)
    _await(lambda: rig.port._hang_s == 0.0, "get_frame начал зависание")
    time.sleep(0.05)
    _call(lambda: session.apply([_step("trigger_period_ms", trigger_period_ms=61)], "restart"))
    _call(lambda: session.apply([_step("trigger_period_ms", trigger_period_ms=62)], "restart"))
    _wait_regrab_done(session, rig.port, "trigger_period_ms", 62, starts=2)
    names = _names(rig.port)
    assert names.count("stop_grabbing") == 1
    assert "set_param(TriggerSelfTriggerPeriod,61)" not in names
    assert "set_param(TriggerSelfTriggerPeriod,62)" in names


# -- строка 6: ящик `call` — результат в потоке владельца, срок, closed --------------------------


def test_call_результат_в_потоке_владельца_срок_и_closed(rig):
    session = rig.make(run=_run_plan(40))
    assert rig.start(session) is True
    owner_id = next(tid for name, _args, tid in list(rig.port.calls) if name == "open")
    assert _call(lambda: session.call(lambda: threading.get_ident(), 1.0)) == (True, owner_id)

    executed: list[str] = []
    rig.port.arm_hang(0.5)
    _await(lambda: rig.port._hang_s == 0.0, "get_frame начал зависание")
    frames_before = _count(rig.port, "get_frame")
    t0 = time.monotonic()
    result = _call(lambda: session.call(lambda: executed.append("fn"), 0.05))
    elapsed = time.monotonic() - t0
    assert result[0] is False
    assert elapsed <= 0.3  # срок 0.05 с, зависание 0.5 с: ответ не ждёт зависания
    _await(lambda: _count(rig.port, "get_frame") >= frames_before + 2, "владелец вернулся из get_frame")
    time.sleep(0.05)
    assert executed == []  # отменённая команда не исполняется и позже

    rig.stop_and_wait(session)
    t0 = time.monotonic()
    closed_result = _call(lambda: session.call(lambda: executed.append("fn2"), 1.0))
    assert closed_result[0] is False
    assert time.monotonic() - t0 <= 0.5  # сразу, не по сроку
    assert executed == []


# -- строка 6: `call` перед `stop()` получает ответ ----------------------------------------------


def test_call_перед_stop_получает_ответ_не_позже_возврата_stop(rig):
    session = rig.make(run=_run_plan(40))
    assert rig.start(session) is True
    rig.port.arm_hang(0.4)
    _await(lambda: rig.port._hang_s == 0.0, "get_frame начал зависание")
    box: dict = {}

    def do_call() -> None:
        try:
            box["result"] = session.call(lambda: "x", 5.0)
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc
        box["t"] = time.monotonic()

    caller = threading.Thread(target=do_call, daemon=True)
    caller.start()
    time.sleep(0.05)
    _call(lambda: session.stop(2.0))
    t_stop = time.monotonic()
    caller.join(3.0)
    assert not caller.is_alive(), "call перед stop() остался без ответа"
    assert "error" not in box, repr(box.get("error"))
    assert box["t"] <= t_stop + 0.3  # ответ владельца или «сеанс остановлен», но не срок 5 с
    assert isinstance(box["result"], tuple) and len(box["result"]) == 2
    assert isinstance(box["result"][0], bool)


# -- строка 8: last_error ------------------------------------------------------------------------


def test_last_error_непусто_после_отказа_и_сброшено_успешным_start(rig):
    created = time.monotonic()
    session = rig.make(run=_run_plan(40), busy_for_s=0.3)
    assert rig.start(session) is False
    assert session.state == "busy"
    assert isinstance(session.last_error, str) and session.last_error
    _await(lambda: not session.device_held, "владелец вышел после отказа open")
    time.sleep(max(0.0, 0.45 - (time.monotonic() - created)))  # фейк перестаёт быть занятым
    assert rig.start(session) is True
    assert session.last_error is None
