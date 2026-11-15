# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты профилей run/rest и проверки чтением (Task 2.2, RED до кода; автор — тестер).

Источник — блоки DESIGN и ACCEPTANCE `plans/2026-10-18_camera-device-service/tasks/2.2.md`.
Ожидаемые значения — литералы из ACCEPTANCE, не вычисляются из кода под тестом.
Журнал порта сравнивается после фильтра по `_KEPT` (отбрасываются `acquire`, `enum_devices`, `describe_param`,
`release`, `get_frame`); записи журнала сведены в строки `set_param(Узел,значение)`, `get_param(Узел)`.
Любой вызов, который может зависнуть (`start`/`stop`), идёт в daemon-потоке с дедлайном `join`;
в teardown фикстуры `rig` всегда `stop()`. `frame_period_s=0.01` во всех тестах (иначе цикл кадров горячий).
Планы run/rest собираются руками из `Step`; узлы и привязки взяты из фейка (`TriggerMode`, `TriggerSource`,
`TriggerSelfTriggerPeriod`, `ExposureTime`).
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import pytest

from Services.camera_device.interface import Binding
from Services.camera_device.params import Step
from Services.camera_device.session import DeviceSession
from Services.camera_device.testing.fake_port import ALL_CAPABILITIES, from_recording, make_port

SESSION_LOGGER = "camera_device.session"
RECORDING = Path(__file__).resolve().parents[1] / "testing" / "recordings" / "mvs_MV-CS020-10GC.json"

# Фильтр журнала из ACCEPTANCE.
_KEPT = {"open", "set_param", "get_param", "start_grabbing", "stop_grabbing", "close"}

B_MODE = Binding("genicam", "TriggerMode", "enum")
B_SOURCE = Binding("genicam", "TriggerSource", "enum")
B_PERIOD = Binding("genicam", "TriggerSelfTriggerPeriod", "int")
B_EXPOSURE = Binding("genicam", "ExposureTime", "float")

NO_RESTART_REGRAB = ALL_CAPABILITIES - {"restart_regrab"}
NO_READ_BACK = ALL_CAPABILITIES - {"read_back"}


def _mode(value: object, *, skip: str | None = None) -> Step:
    return Step("trigger_mode", B_MODE, value, skip, None)


def _source(value: object, *, skip: str | None = None) -> Step:
    return Step("trigger_source", B_SOURCE, value, skip, "trigger_mode")


def _period(value: object, *, skip: str | None = None) -> Step:
    return Step("trigger_period_ms", B_PERIOD, value, skip, "trigger_source")


def _exposure(value: object) -> Step:
    return Step("exposure_time", B_EXPOSURE, value, None, None)


def _chain(period: object) -> list[Step]:
    """Цепочка `{On, SelfTrigger, period}`: период открывается в фейке только при `On` и `SelfTrigger`."""
    return [_mode("On"), _source("SelfTrigger"), _period(period)]


def _log(port) -> list[str]:
    """Журнал порта после фильтра ACCEPTANCE: `open`, `set_param(Узел,значение)`, `get_param(Узел)`, ..."""
    out: list[str] = []
    for name, args, _tid in list(port.calls):
        if name not in _KEPT:
            continue
        if name == "set_param":
            out.append(f"set_param({args[0]},{args[1]})")
        elif name == "get_param":
            out.append(f"get_param({args[0]})")
        else:
            out.append(name)
    return out


def _await(pred, message: str, deadline: float = 2.0) -> None:
    """Опрос с дедлайном вместо `sleep`: `closed` приходит из потока владельца."""
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
    """Сеансы теста: в teardown каждый гасится `stop()` с дедлайном."""

    def __init__(self) -> None:
        self.sessions: list[DeviceSession] = []
        self.port = None

    def make(self, *, run=(), rest=(), port=None, **port_opts) -> DeviceSession:
        port_opts.setdefault("frame_period_s", 0.01)
        self.port = port if port is not None else make_port(**port_opts)
        session = DeviceSession(
            self.port,
            self.port.sdk,
            None,
            timeout_ms=500,
            watchdog_s=5.0,
            on_frame=lambda frame: None,
            run=tuple(run),
            rest=tuple(rest),
        )
        self.sessions.append(session)
        return session

    def start(self, session: DeviceSession) -> bool:
        return _call(lambda: session.start(5.0))

    def stop_and_wait(self, session: DeviceSession) -> None:
        _call(lambda: session.stop(2.0))
        _await(lambda: session.state == "closed", "state == closed после stop")

    def run_cycle(self, session: DeviceSession) -> bool:
        started = self.start(session)
        self.stop_and_wait(session)
        return started


@pytest.fixture
def rig():
    r = _Rig()
    yield r
    for session in r.sessions:
        try:
            _call(lambda s=session: s.stop(2.0))
        except Exception:  # noqa: BLE001 — teardown не маскирует падение теста
            pass


@pytest.fixture
def session_log(caplog):
    caplog.set_level(logging.INFO, logger=SESSION_LOGGER)
    return caplog


# -- run ----------------------------------------------------------------------------------------


def test_run_порядок(rig):
    session = rig.make(run=_chain(40))
    assert rig.start(session) is True
    names = _log(rig.port)
    upto = names.index("start_grabbing") + 1
    assert names[:upto] == [
        "open",
        "set_param(TriggerMode,On)",
        "get_param(TriggerMode)",
        "set_param(TriggerSource,SelfTrigger)",
        "get_param(TriggerSource)",
        "set_param(TriggerSelfTriggerPeriod,40)",
        "get_param(TriggerSelfTriggerPeriod)",
        "start_grabbing",
    ]
    first_set = names.index("set_param(TriggerMode,On)")
    assert "get_param(TriggerMode)" not in names[:first_set]
    assert [n for n in names[:first_set] if n.startswith("get_param")] == []


def test_h5_записалось_с_ошибкой(rig, session_log):
    session = rig.make(run=[_mode("On")], applied_but_error=frozenset({"TriggerMode"}))
    assert rig.start(session) is True
    assert session.param_errors == {}
    assert session.errors == 0
    assert session.params["trigger_mode"] == "On"
    assert session.params_status["trigger_mode"] == {"verified": True, "rc": "network"}
    warnings = [
        r
        for r in session_log.records
        if r.name == SESSION_LOGGER and r.levelno == logging.WARNING and "значение на месте" in r.getMessage()
    ]
    assert warnings, "нет WARNING со словами «значение на месте» от camera_device.session"


def test_допуск_inc(rig):
    # int, inc=1: цель 40, чтение 41 -> не подтвердилось.
    miss = rig.make(run=_chain(40), read_offset={"TriggerSelfTriggerPeriod": 1})
    assert rig.start(miss) is True
    assert miss.param_errors == {"trigger_period_ms": "не подтвердилось чтением"}
    rig.stop_and_wait(miss)

    # int, inc=1: цель 40, чтение 40 -> подтверждено.
    hit = rig.make(run=_chain(40))
    assert rig.start(hit) is True
    assert hit.param_errors == {}
    assert hit.params_status["trigger_period_ms"]["verified"] is True
    rig.stop_and_wait(hit)

    # float, inc=1.0: цель 100.5, фейк пишет floor -> 100.0 -> подтверждено (член inc спасает от 0.5 > 0.1005).
    f1 = rig.make(run=[_exposure(100.5)])
    assert rig.start(f1) is True
    assert f1.param_errors == {}
    assert f1.params["exposure_time"] == 100.0
    assert f1.params_status["exposure_time"]["verified"] is True
    rig.stop_and_wait(f1)

    # float, inc=1.0: цель 1234.5 -> 1234.0 -> подтверждено.
    f2 = rig.make(run=[_exposure(1234.5)])
    assert rig.start(f2) is True
    assert f2.param_errors == {}
    assert f2.params["exposure_time"] == 1234.0
    assert f2.params_status["exposure_time"]["verified"] is True


def test_допуск_ноль_eps_abs(rig):
    # запись mvs_MV-CS020-10GC.json: ExposureTime без шага (inc=None), float.
    near = rig.make(
        run=[_exposure(0.0)], port=from_recording(RECORDING, frame_period_s=0.01, read_offset={"ExposureTime": 1e-7})
    )
    assert rig.start(near) is True
    assert near.param_errors == {}
    assert near.params_status["exposure_time"]["verified"] is True
    rig.stop_and_wait(near)

    far = rig.make(
        run=[_exposure(0.0)], port=from_recording(RECORDING, frame_period_s=0.01, read_offset={"ExposureTime": 0.01})
    )
    assert rig.start(far) is True
    assert far.param_errors == {"exposure_time": "не подтвердилось чтением"}


def test_off_не_теряется(rig):
    # `{managed, Off}`: TriggerMode=Off пишется, потомки пропущены (skip) и в прибор не пишутся.
    off = rig.make(
        run=[
            _mode("Off"),
            _source(None, skip="не нужен: TriggerMode=Off"),
            _period(None, skip="не нужен: TriggerMode=Off"),
        ]
    )
    assert rig.start(off) is True
    names = _log(rig.port)
    assert "set_param(TriggerMode,Off)" in names
    assert [n for n in names if n.startswith("set_param(TriggerSource")] == []
    assert [n for n in names if n.startswith("set_param(TriggerSelfTriggerPeriod")] == []
    rig.stop_and_wait(off)

    # ловушка 1.6: int 0 — значение, а не отсутствие; цепочка открывает узел периода.
    zero = rig.make(run=_chain(0))
    assert rig.start(zero) is True
    assert "set_param(TriggerSelfTriggerPeriod,0)" in _log(rig.port)
    assert zero.params["trigger_period_ms"] == 0
    assert zero.param_errors == {}


def test_без_read_back(rig):
    session = rig.make(run=[_exposure(900.0)], capabilities=NO_READ_BACK)
    assert rig.start(session) is True
    assert session.params["exposure_time"] == 900.0
    assert session.params_status["exposure_time"] == {"verified": False, "rc": None}
    assert session.param_errors == {}
    assert [n for n in _log(rig.port) if n.startswith("get_param")] == []


# -- rest ---------------------------------------------------------------------------------------


def test_rest_neter(rig, session_log):
    rest = [_mode("On"), _source("Line0")]
    session = rig.make(rest=rest, neter_after_stop=True)  # restart_regrab есть среди capabilities
    assert rig.run_cycle(session) is True
    assert session.param_errors == {"trigger_mode": "network"}
    assert session.errors == 1
    names = _log(rig.port)
    assert [n for n in names if n.startswith("set_param(TriggerSource")] == []
    assert names.count("close") == 1
    skips = [
        r
        for r in session_log.records
        if r.name == SESSION_LOGGER and "skip=пропущен: родитель не записан" in r.getMessage()
    ]
    assert skips, "нет INFO-записи skip=пропущен: родитель не записан"


def test_rest_порядок_restart_regrab(rig):
    session = rig.make(rest=[_mode("On"), _source("Line0")])
    assert rig.run_cycle(session) is True
    names = _log(rig.port)
    last_stop = len(names) - 1 - names[::-1].index("stop_grabbing")
    assert names[last_stop:] == [
        "stop_grabbing",
        "set_param(TriggerMode,On)",
        "get_param(TriggerMode)",
        "set_param(TriggerSource,Line0)",
        "get_param(TriggerSource)",
        "close",
    ]
    assert session.param_errors == {}


def test_rest_ветка_reopen(rig):
    # neter_after_stop без restart_regrab: `close` снимает NETER, поэтому rest идёт на втором open.
    session = rig.make(rest=[_mode("On"), _source("Line0")], neter_after_stop=True, capabilities=NO_RESTART_REGRAB)
    assert rig.run_cycle(session) is True
    names = _log(rig.port)
    last_stop = len(names) - 1 - names[::-1].index("stop_grabbing")
    last_close = len(names) - 1 - names[::-1].index("close")
    assert names[last_stop : last_close + 1] == [
        "stop_grabbing",
        "close",
        "open",
        "set_param(TriggerMode,On)",
        "get_param(TriggerMode)",
        "set_param(TriggerSource,Line0)",
        "get_param(TriggerSource)",
        "close",
    ]
    assert session.param_errors == {}
    assert session.errors == 0


def test_второй_старт_после_отказа_rest(rig):
    session = rig.make(run=_chain(40), rest=[_mode("On"), _source("Line0")], neter_after_stop=True)
    assert rig.run_cycle(session) is True
    # TriggerMode уже On по чтению (H5 «на месте»); TriggerSource отказал под NETER и остался SelfTrigger.
    assert session.param_errors == {"trigger_source": "network"}
    assert session.errors == 1
    _await(lambda: not session.device_held, "владелец первого цикла вышел")

    assert rig.start(session) is True
    names = _log(rig.port)
    second_open = len(names) - 1 - names[::-1].index("open")
    second_grab = names.index("start_grabbing", second_open)
    assert names[second_open : second_grab + 1] == [
        "open",
        "set_param(TriggerMode,On)",
        "get_param(TriggerMode)",
        "set_param(TriggerSource,SelfTrigger)",
        "get_param(TriggerSource)",
        "set_param(TriggerSelfTriggerPeriod,40)",
        "get_param(TriggerSelfTriggerPeriod)",
        "start_grabbing",
    ]
    assert session.param_errors == {}
    assert session.errors == 1  # счётчик не сбрасывается start()
