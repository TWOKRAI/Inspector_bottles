# -*- coding: utf-8 -*-
"""Hazard-тесты автора Task 2.4a: ящик владельца, `apply`, перезахват внутри `grabbing`.

Гонки и порядок: `stop()` в окне перезахвата, отказ `open`/`start_grabbing` перезахвата, исключение `fn` команды,
`call` из потока владельца и по сроку при уже исполняющейся команде, слияние правок одного поля, утечка очереди
между циклами, наблюдаемость (`on_timing`, лог). Ожидаемые значения — литералы. Любой вызов, который может
зависнуть, идёт в daemon-потоке с дедлайном `join`; в teardown фикстуры всегда `stop()`.
"""

from __future__ import annotations

import logging
import threading
import time

import pytest

from Services.camera_device.interface import PortError
from Services.camera_device.params import Step, build_plan
from Services.camera_device.registers_base import CameraDeviceRegisters
from Services.camera_device.session import DeviceSession
from Services.camera_device.testing.fake_port import ALL_CAPABILITIES, FAKE_BINDINGS, make_port
from multiprocess_framework.modules.worker_module import WorkerManager

_KEPT = {"open", "set_param", "get_param", "start_grabbing", "stop_grabbing", "close"}
NO_RESTART_REGRAB = ALL_CAPABILITIES - {"restart_regrab"}


def _values(**overrides) -> dict:
    return CameraDeviceRegisters(
        trigger_managed=True, trigger_mode="On", trigger_source="SelfTrigger", **overrides
    ).model_dump()


def _step(field: str, **overrides) -> Step:
    return next(s for s in build_plan(CameraDeviceRegisters, _values(**overrides), FAKE_BINDINGS) if s.field == field)


def _plan(**values) -> list[Step]:
    """План из полей register'а, группа `trigger_managed: true`; значения полей — как заданы, остальные — умолчания."""
    registers = CameraDeviceRegisters(trigger_managed=True, **values).model_dump()
    return build_plan(CameraDeviceRegisters, registers, FAKE_BINDINGS)


def _run_plan(period: int = 40) -> list[Step]:
    return build_plan(CameraDeviceRegisters, _values(trigger_period_ms=period), FAKE_BINDINGS)


def _names(port) -> list[str]:
    out: list[str] = []
    for name, args, _tid in list(port.calls):
        if name not in _KEPT:
            continue
        out.append(f"set_param({args[0]},{args[1]})" if name == "set_param" else name)
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


def _bg(fn):
    """`fn` в daemon-потоке без ожидания: `(поток, {"result": ...})`; для `start()`, пока тест правит сеанс."""
    box: dict = {}

    def run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — исключение возвращается тесту
            box["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    return worker, box


def _join(worker, box, deadline: float = 4.0):
    worker.join(deadline)
    assert not worker.is_alive(), f"поток не вернулся за {deadline} с"
    if "error" in box:
        raise box["error"]
    return box.get("result")


def _await_opening(rig, session) -> None:
    """Владелец в `open` (он спит `open_delay_s`), состояние `opening`."""
    _await(lambda: session.state == "opening" and _count(rig.port, "open") == 1, "владелец в open, state opening")


class _Rig:
    def __init__(self) -> None:
        self.sessions: list[DeviceSession] = []
        self.port = None
        self.events: list[tuple[str, str]] = []
        self.timings: list[tuple[str, float]] = []
        self.wm = WorkerManager("test_cam_live_hazards")

    def make(self, *, run=(), rest=(), on_frame=None, **port_opts) -> DeviceSession:
        port_opts.setdefault("frame_period_s", 0.01)
        self.port = make_port(**port_opts)
        session = DeviceSession(
            self.port,
            self.port.sdk,
            None,
            timeout_ms=500,
            watchdog_s=5.0,
            on_frame=on_frame or (lambda frame: None),
            on_state=lambda old, new: self.events.append((old, new)),
            on_timing=lambda name, seconds: self.timings.append((name, seconds)),
            workers=self.wm,
            worker_prefix=f"camera_device_hz_{len(self.sessions)}",
            run=tuple(run),
            rest=tuple(rest),
        )
        self.sessions.append(session)
        return session

    def start(self, session: DeviceSession) -> bool:
        return _call(lambda: session.start(5.0))

    def hang(self, seconds: float) -> None:
        """Зависание ближайшего `get_frame`; возврат, когда оно уже началось."""
        self.port.arm_hang(seconds)
        _await(lambda: self.port._hang_s == 0.0, "get_frame начал зависание")


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


# -- stop() в окне перезахвата --------------------------------------------------------------------


def test_stop_в_окне_перезахвата_закрывает_порт_и_не_зовёт_start_grabbing(rig):
    session = rig.make(run=_run_plan(40), capabilities=NO_RESTART_REGRAB, open_delay_s=0.3)
    assert rig.start(session) is True
    _call(lambda: session.apply([_step("trigger_period_ms", trigger_period_ms=60)], "restart"))
    _await(lambda: _names(rig.port).count("open") == 2, "перезахват дошёл до open (он спит 0,3 с)")
    _call(lambda: session.stop(0.1))
    _await(lambda: session.state == "closed" and not session.device_held, "closed и held False после стопа")
    names = _names(rig.port)
    assert names.count("start_grabbing") == 1  # после стопа второй start_grabbing не зовётся
    assert names[names.index("start_grabbing") + 1 :] == ["stop_grabbing", "close", "open", "close"]
    assert rig.port.open_handles == 0
    assert rig.events == [
        ("idle", "opening"),
        ("opening", "grabbing"),
        ("grabbing", "stopping"),
        ("stopping", "closed"),
    ]


def test_стоп_до_перезахвата_команда_не_исполняется_и_порт_не_трогается_apply(rig):
    session = rig.make(run=_run_plan(40))
    assert rig.start(session) is True
    rig.hang(0.3)
    _call(lambda: session.apply([_step("trigger_period_ms", trigger_period_ms=61)], "restart"))
    _call(lambda: session.stop(2.0))
    _await(lambda: session.state == "closed", "closed")
    names = _names(rig.port)
    assert "set_param(TriggerSelfTriggerPeriod,61)" not in names
    assert names.count("stop_grabbing") == 1  # один — из `_cleanup`, перезахвата не было
    assert names.count("start_grabbing") == 1


# -- отказ перезахвата -----------------------------------------------------------------------------


def test_отказ_open_перезахвата_error_без_повторного_close(rig):
    session = rig.make(run=_run_plan(40), capabilities=NO_RESTART_REGRAB)
    assert rig.start(session) is True
    original_open = rig.port.open
    opens: list[int] = []

    def failing_open(ident):
        opens.append(1)
        raise PortError("other", "open")

    rig.port.open = failing_open
    try:
        _call(lambda: session.apply([_step("trigger_period_ms", trigger_period_ms=60)], "restart"))
        _await(lambda: session.state == "error" and not session.device_held, "error и владелец вышел")
    finally:
        rig.port.open = original_open
    assert opens == [1]
    assert isinstance(session.last_error, str) and "PortError" in session.last_error
    assert _count(rig.port, "close") == 1  # закрыл перезахват; `_cleanup` закрытый порт не трогает
    assert _count(rig.port, "stop_grabbing") == 1
    assert _count(rig.port, "release") == 1
    assert rig.events == [("idle", "opening"), ("opening", "grabbing"), ("grabbing", "error")]
    assert rig.port.open_handles == 0


def test_отказ_start_grabbing_перезахвата_error_закрывает_без_лишнего_stop_grabbing(rig):
    session = rig.make(run=_run_plan(40))
    assert rig.start(session) is True
    original = rig.port.start_grabbing

    def failing_start():
        raise PortError("other", "start_grabbing")

    rig.port.start_grabbing = failing_start
    try:
        _call(lambda: session.apply([_step("trigger_period_ms", trigger_period_ms=60)], "restart"))
        _await(lambda: session.state == "error" and not session.device_held, "error и владелец вышел")
    finally:
        rig.port.start_grabbing = original
    assert _count(rig.port, "stop_grabbing") == 1  # перезахвата; порт уже остановлен — `_cleanup` второй раз не зовёт
    assert _count(rig.port, "close") == 1
    assert rig.port.open_handles == 0
    assert session.last_error is not None


# -- ящик: исключение fn, submit, срок, поток владельца -------------------------------------------


@pytest.mark.parametrize(
    ("exc_type", "answer"),
    [(RuntimeError, "RuntimeError"), (ZeroDivisionError, "ZeroDivisionError"), (KeyError, "KeyError")],
)
def test_исключение_fn_не_валит_цикл_и_отвечает_отказом(rig, exc_type, answer):
    session = rig.make(run=_run_plan(40))
    assert rig.start(session) is True

    def boom():
        raise exc_type("x")

    assert _call(lambda: session.call(boom, 1.0)) == (False, answer)
    frames = _count(rig.port, "get_frame")
    assert _call(lambda: session.call(lambda: 7, 1.0)) == (True, 7)  # владелец жив и опрашивает ящик
    _await(lambda: _count(rig.port, "get_frame") > frames, "кадры идут после исключения fn")
    assert session.state == "grabbing"
    assert session.device_held is True
    assert rig.events == [("idle", "opening"), ("opening", "grabbing")]


def test_submit_не_в_захвате_возвращает_false_и_в_захвате_исполняет_в_потоке_владельца(rig):
    session = rig.make(run=_run_plan(40))
    assert session.submit(lambda: None) is False  # idle
    assert rig.start(session) is True
    owner_id = next(tid for name, _args, tid in list(rig.port.calls) if name == "open")
    seen: list[int] = []
    assert session.submit(lambda: seen.append(threading.get_ident())) is True
    _await(lambda: seen != [], "fn исполнена владельцем")
    assert seen == [owner_id]
    _call(lambda: session.stop(2.0))
    _await(lambda: session.state == "closed", "closed")
    assert session.submit(lambda: seen.append(0)) is False  # closed
    time.sleep(0.05)
    assert seen == [owner_id]


def test_call_по_сроку_при_уже_исполняющейся_команде_ждёт_и_отдаёт_результат(rig):
    session = rig.make(run=_run_plan(40))
    assert rig.start(session) is True

    def slow():
        time.sleep(0.3)
        return "готово"

    t0 = time.monotonic()
    result = _call(lambda: session.call(slow, 0.05))
    elapsed = time.monotonic() - t0
    assert result == (True, "готово")  # команда уже взята владельцем: отмена невозможна, ответ ждём
    assert elapsed >= 0.25


def test_call_из_потока_владельца_не_блокирует(rig):
    results: list[tuple[tuple[bool, object], float]] = []

    def on_frame(frame) -> None:
        if not results:
            t0 = time.monotonic()
            answer = session.call(lambda: 1, 5.0)
            results.append((answer, time.monotonic() - t0))

    session = rig.make(run=_run_plan(40), on_frame=on_frame)
    assert rig.start(session) is True
    _await(lambda: results != [], "on_frame вызвал call")
    ((answer, elapsed),) = results
    assert answer[0] is False
    assert elapsed < 0.5  # сам себя владелец не ждёт
    assert session.state == "grabbing"


def test_call_и_apply_после_stop_отвечают_сразу_без_порта(rig):
    session = rig.make(run=_run_plan(40))
    assert rig.start(session) is True
    _call(lambda: session.stop(2.0))
    _await(lambda: session.state == "closed", "closed")
    before = len(rig.port.calls)
    t0 = time.monotonic()
    assert _call(lambda: session.call(lambda: 1, 1.0))[0] is False
    _call(lambda: session.apply([_step("exposure_time", exposure_time=1200.0)], "live"))
    assert time.monotonic() - t0 < 0.5
    assert len(rig.port.calls) == before


def test_live_запись_идёт_из_потока_владельца_а_не_вызывающего(rig):
    session = rig.make(run=_run_plan(40))
    assert rig.start(session) is True
    owner_id = next(tid for name, _args, tid in list(rig.port.calls) if name == "open")
    caller_ids: list[int] = []
    _call(
        lambda: (
            caller_ids.append(threading.get_ident()),
            session.apply([_step("exposure_time", exposure_time=1200.0)], "live"),
        )
    )
    _await(lambda: session.params.get("exposure_time") == 1200.0, "live применён")
    writers = {
        tid for name, args, tid in list(rig.port.calls) if name == "set_param" and args == ("ExposureTime", 1200.0)
    }
    assert writers == {owner_id}
    assert owner_id not in caller_ids


# -- слияние и жизнь очереди ------------------------------------------------------------------------


def test_повторные_apply_одного_поля_за_зависанием_пишут_только_последнее(rig):
    session = rig.make(run=_run_plan(40))
    assert rig.start(session) is True
    rig.hang(0.3)
    for value in (1100.0, 1200.0, 1300.0):
        _call(lambda v=value: session.apply([_step("exposure_time", exposure_time=v)], "live"))
    _await(lambda: session.params.get("exposure_time") == 1300.0, "exposure_time == 1300.0")
    names = _names(rig.port)
    assert [n for n in names if n.startswith("set_param(ExposureTime")] == [
        "set_param(ExposureTime,10000.0)",  # план run при старте
        "set_param(ExposureTime,1300.0)",
    ]
    assert "stop_grabbing" not in names


def test_правка_заменяет_шаг_в_run_и_следующий_перезахват_её_не_откатывает(rig):
    session = rig.make(run=_run_plan(40), capabilities=NO_RESTART_REGRAB)
    assert rig.start(session) is True
    _call(lambda: session.apply([_step("trigger_period_ms", trigger_period_ms=60)], "restart"))
    _await(lambda: _names(rig.port).count("start_grabbing") == 2, "первый перезахват")
    _call(lambda: session.apply([_step("exposure_time", exposure_time=1200.0)], "restart"))
    _await(lambda: _names(rig.port).count("start_grabbing") == 3, "второй перезахват")
    names = _names(rig.port)
    last_open = len(names) - 1 - names[::-1].index("open")
    after = names[last_open:]
    assert "set_param(TriggerSelfTriggerPeriod,60)" in after  # старая правка не откатилась
    assert "set_param(ExposureTime,1200.0)" in after
    assert session.params["trigger_period_ms"] == 60
    assert session.params["exposure_time"] == 1200.0


def test_очередь_не_переходит_в_следующий_цикл(rig):
    session = rig.make(run=_run_plan(40))
    assert rig.start(session) is True
    rig.hang(0.3)
    _call(lambda: session.apply([_step("trigger_period_ms", trigger_period_ms=61)], "restart"))
    _call(lambda: session.stop(2.0))
    _await(lambda: session.state == "closed" and not session.device_held, "closed")
    assert rig.start(session) is True  # новый цикл: новый ящик
    assert session.params["trigger_period_ms"] == 40
    stops_before = _count(rig.port, "stop_grabbing")
    _call(lambda: session.apply([_step("exposure_time", exposure_time=1200.0)], "live"))
    _await(
        lambda: session.params.get("exposure_time") == 1200.0, "apply второго цикла дошёл"
    )  # `_drain_queued` сброшен
    assert _count(rig.port, "stop_grabbing") == stops_before
    assert "set_param(TriggerSelfTriggerPeriod,61)" not in _names(rig.port)


def test_apply_вне_захвата_не_копится_и_не_пишет_в_следующий_цикл(rig):
    session = rig.make(run=_run_plan(40))
    _call(lambda: session.apply([_step("trigger_period_ms", trigger_period_ms=61)], "restart"))  # idle
    assert len(rig.port.calls) == 0
    assert rig.start(session) is True
    time.sleep(0.1)  # окно, в котором остаточная правка успела бы дойти до порта
    assert session.params["trigger_period_ms"] == 40
    assert "stop_grabbing" not in _names(rig.port)


def test_apply_неизвестная_политика_и_пустой_пакет(rig):
    session = rig.make(run=_run_plan(40))
    with pytest.raises(ValueError):
        session.apply([_step("exposure_time", exposure_time=1200.0)], "config")
    session.apply([], "live")  # пустой пакет — не ошибка и не команда
    assert rig.start(session) is True
    assert session.state == "grabbing"


# -- apply в opening (решение лида: правка не теряется) -------------------------------------------


def test_apply_live_в_opening_исполняется_один_раз_до_первого_get_frame(rig):
    session = rig.make(run=_run_plan(40), open_delay_s=0.3)
    worker, box = _bg(lambda: session.start(5.0))
    _await_opening(rig, session)
    _call(lambda: session.apply([_step("exposure_time", exposure_time=1200.0)], "live"))
    assert _join(worker, box) is True
    _await(lambda: session.params.get("exposure_time") == 1200.0, "правка из opening применена")
    calls = [name if name != "set_param" else f"set_param({args[0]},{args[1]})" for name, args, _tid in rig.port.calls]
    assert calls.count("set_param(ExposureTime,1200.0)") == 1
    assert calls.index("set_param(ExposureTime,1200.0)") > calls.index("start_grabbing")  # после входа в grabbing
    first_frame = calls.index("get_frame") if "get_frame" in calls else len(calls)
    assert calls.index("set_param(ExposureTime,1200.0)") < first_frame  # до первого get_frame
    assert "stop_grabbing" not in calls
    assert rig.events == [("idle", "opening"), ("opening", "grabbing")]


def test_apply_restart_в_opening_один_перезахват_после_входа_в_grabbing(rig):
    session = rig.make(run=_run_plan(40), open_delay_s=0.3)
    worker, box = _bg(lambda: session.start(5.0))
    _await_opening(rig, session)
    _call(lambda: session.apply([_step("trigger_period_ms", trigger_period_ms=60)], "restart"))
    assert _join(worker, box) is True
    _await(
        lambda: session.params.get("trigger_period_ms") == 60 and _names(rig.port)[-1:] == ["start_grabbing"],
        "перезахват",
    )
    names = _names(rig.port)
    assert names.count("set_param(TriggerSelfTriggerPeriod,60)") == 1
    assert names[names.index("start_grabbing") + 1 :] == [
        "stop_grabbing",
        "set_param(TriggerSelfTriggerPeriod,60)",
        "get_param",
        "start_grabbing",
    ]
    assert rig.events == [("idle", "opening"), ("opening", "grabbing")]  # перезахват состояния не меняет
    calls = [name for name, _args, _tid in rig.port.calls]
    first_start = calls.index("start_grabbing")
    assert "get_frame" not in calls[first_start : calls.index("stop_grabbing")]  # перезахват до первого get_frame


def test_apply_в_opening_и_сразу_stop_закрывает_без_start_grabbing(rig):
    session = rig.make(run=_run_plan(40), open_delay_s=0.3)
    worker, box = _bg(lambda: session.start(5.0))
    _await_opening(rig, session)
    _call(lambda: session.apply([_step("trigger_period_ms", trigger_period_ms=61)], "restart"))
    _call(lambda: session.stop(2.0))
    assert _join(worker, box) is False
    _await(lambda: session.state == "closed" and not session.device_held, "closed и held False")
    names = _names(rig.port)
    assert "start_grabbing" not in names
    assert "stop_grabbing" not in names
    assert "set_param(TriggerSelfTriggerPeriod,61)" not in names
    assert rig.port.open_handles == 0
    assert rig.events == [("idle", "opening"), ("opening", "stopping"), ("stopping", "closed")]


def test_apply_в_closed_не_принимается_порт_не_зовётся_и_правка_не_копится(rig):
    session = rig.make(run=_run_plan(40))
    assert rig.start(session) is True
    _call(lambda: session.stop(2.0))
    _await(lambda: session.state == "closed" and not session.device_held, "closed")
    before = len(rig.port.calls)
    _call(lambda: session.apply([_step("trigger_period_ms", trigger_period_ms=61)], "restart"))
    time.sleep(0.1)
    assert len(rig.port.calls) == before
    assert rig.start(session) is True  # следующий цикл строится из плана run, остаточной правки нет
    assert session.params["trigger_period_ms"] == 40
    assert _names(rig.port).count("stop_grabbing") == 1  # только из `_cleanup` первого цикла


# -- стоп в разные моменты перезахвата (детерминированно: хук порта зовёт `stop()` из потока владельца) ----


def test_стоп_после_записи_до_start_grabbing_перезахват_не_зовёт_start_grabbing(rig):
    session = rig.make(run=_run_plan(40))  # умолчание фейка: restart_regrab, запись шагов пакета в открытый порт
    assert rig.start(session) is True
    armed = [True]
    original_get_param = rig.port.get_param

    def get_param_then_stop(binding):
        value = original_get_param(binding)
        if armed and binding.key == "TriggerSelfTriggerPeriod":
            armed.clear()
            session.stop(0.1)  # из потока владельца: стоп запрошен посреди записи пакета, возврат сразу
        return value

    rig.port.get_param = get_param_then_stop
    _call(lambda: session.apply([_step("trigger_period_ms", trigger_period_ms=60)], "restart"))
    _await(lambda: session.state == "closed" and not session.device_held, "closed и held False")
    names = _names(rig.port)
    assert names[names.index("start_grabbing") + 1 :] == [
        "stop_grabbing",
        "set_param(TriggerSelfTriggerPeriod,60)",
        "get_param",
        "close",
    ]  # второго start_grabbing нет; `_cleanup` не зовёт stop_grabbing остановленного порта
    assert rig.port.open_handles == 0


def test_стоп_между_close_и_open_перезахвата_rest_не_пишется_в_закрытый_порт(rig):
    session = rig.make(run=_run_plan(40), rest=_run_plan(99), capabilities=NO_RESTART_REGRAB)
    assert rig.start(session) is True
    armed = [True]
    original_close = rig.port.close

    def close_then_stop():
        original_close()
        if armed:
            armed.clear()
            session.stop(0.1)  # порт закрыт, `open` перезахвата ещё не начат

    rig.port.close = close_then_stop
    _call(lambda: session.apply([_step("trigger_period_ms", trigger_period_ms=60)], "restart"))
    _await(lambda: session.state == "closed" and not session.device_held, "closed и held False")
    names = _names(rig.port)
    assert names[names.index("start_grabbing") + 1 :] == [
        "stop_grabbing",
        "close",
    ]  # нет open, нет rest, нет второго close
    assert "set_param(TriggerSelfTriggerPeriod,99)" not in names
    assert session.errors == 0  # запись rest в закрытый порт дала бы отказы узлов
    assert rig.port.open_handles == 0


def test_правка_из_opening_цикла_1_не_попадает_в_прибор_цикла_2(rig):
    session = rig.make(run=_run_plan(40), open_delay_s=0.3)
    worker, box = _bg(lambda: session.start(5.0))
    _await_opening(rig, session)
    _call(lambda: session.apply([_step("trigger_period_ms", trigger_period_ms=61)], "restart"))
    _call(lambda: session.stop(2.0))
    assert _join(worker, box) is False
    _await(lambda: session.state == "closed" and not session.device_held, "цикл 1 закрыт")
    assert rig.start(session) is True  # цикл 2
    _call(lambda: session.apply([_step("exposure_time", exposure_time=1200.0)], "live"))
    _await(lambda: session.params.get("exposure_time") == 1200.0, "правка цикла 2 применена")
    names = _names(rig.port)
    assert "set_param(TriggerSelfTriggerPeriod,61)" not in names  # правка цикла 1 в прибор цикла 2 не попала
    assert "stop_grabbing" not in names
    assert session.params["trigger_period_ms"] == 40


# -- порядок «родитель раньше потомка» в слитом пакете правок --------------------------------------------


def _wait_regrab_end(rig) -> None:
    """Перезахват завершён: второй `start_grabbing` последний в журнале (значение поля не ждём: при отказе его нет)."""
    _await(
        lambda: _names(rig.port)[-1:] == ["start_grabbing"] and _names(rig.port).count("start_grabbing") >= 2,
        "перезахват завершён",
    )


def test_пакет_потомок_и_родитель_с_restart_regrab_пишется_родитель_раньше_потомка(rig):
    # `trigger_source` открывает узел периода, пока он не `SelfTrigger`, период закрыт; в пакете потомок пришёл первым
    session = rig.make(run=_plan(trigger_mode="On", trigger_source="Line0"))
    assert rig.start(session) is True
    rig.hang(0.3)  # обе правки ложатся в один пакет
    period = _step("trigger_period_ms", trigger_period_ms=60)
    source = _step("trigger_source")
    _call(lambda: session.apply([period], "restart"))
    _call(lambda: session.apply([source], "restart"))
    _wait_regrab_end(rig)
    names = _names(rig.port)
    assert names[names.index("start_grabbing") + 1 :] == [
        "stop_grabbing",
        "set_param(TriggerSource,SelfTrigger)",
        "get_param",
        "set_param(TriggerSelfTriggerPeriod,60)",
        "get_param",
        "start_grabbing",
    ]
    assert session.param_errors == {}
    assert session.params["trigger_source"] == "SelfTrigger"
    assert session.params["trigger_period_ms"] == 60


def test_пакет_потомок_и_родитель_без_restart_regrab_run_цикла_в_порядке_родитель_потомок(rig):
    session = rig.make(run=_plan(trigger_mode="On", trigger_source="Line0"), capabilities=NO_RESTART_REGRAB)
    assert rig.start(session) is True
    rig.hang(0.3)
    _call(lambda: session.apply([_step("trigger_period_ms", trigger_period_ms=60)], "restart"))
    _call(lambda: session.apply([_step("trigger_source")], "restart"))
    _wait_regrab_end(rig)
    names = _names(rig.port)
    assert names[names.index("start_grabbing") + 1 :] == [
        "stop_grabbing",
        "close",
        "open",
        "set_param(TriggerMode,On)",
        "get_param",
        "set_param(TriggerSource,SelfTrigger)",
        "get_param",
        "set_param(TriggerSelfTriggerPeriod,60)",
        "get_param",
        "set_param(ExposureTime,10000.0)",
        "get_param",
        "start_grabbing",
    ]
    assert session.param_errors == {}


def test_пакет_источник_и_режим_триггера_режим_пишется_раньше_источника(rig):
    # режим `Off` закрывает узел источника; шаг источника пришёл раньше шага режима
    session = rig.make(run=_plan(trigger_mode="Off", trigger_source="SelfTrigger"))
    assert rig.start(session) is True
    rig.hang(0.3)
    on = _plan(trigger_mode="On", trigger_source="SelfTrigger")
    _call(lambda: session.apply([next(step for step in on if step.field == "trigger_source")], "restart"))
    _call(lambda: session.apply([next(step for step in on if step.field == "trigger_mode")], "restart"))
    _wait_regrab_end(rig)
    names = _names(rig.port)
    assert names[names.index("start_grabbing") + 1 :] == [
        "stop_grabbing",
        "set_param(TriggerMode,On)",
        "get_param",
        "set_param(TriggerSource,SelfTrigger)",
        "get_param",
        "start_grabbing",
    ]
    assert session.param_errors == {}
    assert session.params["trigger_mode"] == "On"


# -- наблюдаемость ---------------------------------------------------------------------------------


def test_on_timing_regrab_и_apply_и_строка_лога_с_политикой(rig, caplog):
    session = rig.make(run=_run_plan(40))
    assert rig.start(session) is True
    with caplog.at_level(logging.INFO, logger="camera_device.session"):
        _call(lambda: session.apply([_step("exposure_time", exposure_time=1200.0)], "live"))
        _await(lambda: session.params.get("exposure_time") == 1200.0, "live применён")
        _call(lambda: session.apply([_step("trigger_period_ms", trigger_period_ms=60)], "restart"))
        _await(lambda: any(n == "regrab" for n, _s in rig.timings), "on_timing regrab")
    names = [n for n, _s in rig.timings]
    assert "regrab" in names
    assert names.count("apply") >= 2  # запись `exposure_time` и запись `trigger_period_ms`
    assert all(isinstance(seconds, float) and seconds >= 0 for _n, seconds in rig.timings)
    messages = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("apply field=exposure_time policy=live ms=") for m in messages)
    assert any(m.startswith("apply field=trigger_period_ms policy=restart ms=") for m in messages)
