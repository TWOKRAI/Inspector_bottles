# -*- coding: utf-8 -*-
"""Hazard-тесты профилей run/rest (Task 2.2, автор — исполнитель): то, что слепой файл не уместил в лимит.

Отказы узлов моделируются обёрткой над методами фейкового порта в самом тесте (фейк не правится).
Ожидаемые значения — литералы из ACCEPTANCE/DESIGN задачи 2.2.
"""

from __future__ import annotations

import logging
import threading
import time

import pytest

from Services.camera_device.interface import Binding, DeviceIdentity, PortError
from Services.camera_device.params import Step, build_plan
from Services.camera_device.profiles import ProfileRunner, ProfileState
from Services.camera_device.session import DeviceSession
from multiprocess_framework.modules.worker_module import WorkerManager
from Services.camera_device.testing.fake_port import ALL_CAPABILITIES, make_port
from Services.camera_device.tests.test_params import BINDINGS, TriggerRegister

SESSION_LOGGER = "camera_device.session"
B_MODE = Binding("genicam", "TriggerMode", "enum")
B_SOURCE = Binding("genicam", "TriggerSource", "enum")
B_PERIOD = Binding("genicam", "TriggerSelfTriggerPeriod", "int")
NO_RESTART_REGRAB = ALL_CAPABILITIES - {"restart_regrab"}
NO_READ_BACK = ALL_CAPABILITIES - {"read_back"}


def _mode(value, skip=None) -> Step:
    return Step("trigger_mode", B_MODE, value, skip, None)


def _source(value, skip=None) -> Step:
    return Step("trigger_source", B_SOURCE, value, skip, "trigger_mode")


def _period(value, skip=None) -> Step:
    return Step("trigger_period_ms", B_PERIOD, value, skip, "trigger_source")


def _chain(period) -> list[Step]:
    return [_mode("On"), _source("SelfTrigger"), _period(period)]


def _names(port) -> list[str]:
    return [f"{c[0]}({c[1][0]})" if c[0] in ("set_param", "get_param") else c[0] for c in list(port.calls)]


def _await(pred, message: str, deadline: float = 2.0) -> None:
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if pred():
            return
        time.sleep(0.005)
    assert pred(), f"не дождались за {deadline} с: {message}"


def _refuse(port, key: str, kind: str = "access") -> None:
    """`set_param` узла `key` отказывает до записи: значение узла не меняется."""
    original = port.set_param

    def set_param(b, value):
        if b.key == key:
            port._record("set_param", (b.key, value))
            raise PortError(kind, "set_param")
        return original(b, value)

    port.set_param = set_param


def _read_raises(port, key: str, kind: str = "timeout") -> None:
    original = port.get_param

    def get_param(b):
        if b.key == key:
            port._record("get_param", (b.key,))
            raise PortError(kind, "get_param")
        return original(b)

    port.get_param = get_param


class _Rig:
    def __init__(self) -> None:
        self.sessions: list[DeviceSession] = []
        self.wm = WorkerManager("test_cam")
        self.timings: list[tuple[str, float]] = []

    def make(self, *, port=None, run=(), rest=(), timeout_ms=500, watchdog_s=5.0, **opts) -> DeviceSession:
        opts.setdefault("frame_period_s", 0.01)
        self.port = port if port is not None else make_port(**opts)
        self.stalls: list[tuple[str, float]] = []
        session = DeviceSession(
            self.port,
            self.port.sdk,
            None,
            timeout_ms=timeout_ms,
            watchdog_s=watchdog_s,
            on_stall=lambda call, seconds: self.stalls.append((call, seconds)),
            on_frame=lambda frame: None,
            workers=self.wm,
            worker_prefix=f"camera_device_{len(self.sessions)}",
            on_timing=lambda name, seconds: self.timings.append((name, seconds)),
            run=tuple(run),
            rest=tuple(rest),
        )
        self.sessions.append(session)
        return session

    def cycle(self, session: DeviceSession) -> bool:
        started = session.start(3.0)
        session.stop(2.0)
        _await(lambda: session.state == "closed", "state == closed")
        return started


@pytest.fixture
def rig():
    r = _Rig()
    yield r
    for session in r.sessions:
        session.stop(2.0)
    me = threading.current_thread()
    for thread in threading.enumerate():
        if thread is not me and thread.name.startswith("test_cam_"):
            thread.join(3.0)
    r.wm.stop_all_workers(2.0)


@pytest.fixture
def session_log(caplog):
    caplog.set_level(logging.INFO, logger=SESSION_LOGGER)
    return caplog


def test_rest_neter_реальный_план(rig):
    values = {"trigger_managed": True, "trigger_mode": "On", "trigger_source": "Line0", "trigger_period_ms": 40}
    plan = build_plan(TriggerRegister, values, BINDINGS)  # родитель шагов — не флаг группы
    session = rig.make(rest=plan, neter_after_stop=True)
    assert rig.cycle(session) is True
    assert session.param_errors == {"trigger_mode": "network"}
    assert session.errors == 1
    assert not [n for n in _names(rig.port) if n.startswith("set_param(TriggerSource")]


def test_родитель_отказал_потомки_и_внук_не_пишутся_errors_1(rig):
    port = make_port(frame_period_s=0.01)
    _refuse(port, "TriggerMode")
    session = rig.make(port=port, run=_chain(40))
    assert session.start(3.0) is True  # отказ узла run не мешает start_grabbing
    assert "start_grabbing" in _names(port)
    names = _names(port)
    assert not [n for n in names if n.startswith("set_param(TriggerSource") or n.startswith("set_param(TriggerSelf")]
    assert session.param_errors == {"trigger_mode": "access"}
    assert session.errors == 1  # потомок и внук не растят счётчик


def test_чтение_упало(rig):
    port = make_port(frame_period_s=0.01)
    _read_raises(port, "TriggerMode", "timeout")
    session = rig.make(port=port, run=[_mode("On")])
    assert session.start(3.0) is True
    assert session.param_errors == {"trigger_mode": "чтение не удалось: timeout"}
    assert session.params_status["trigger_mode"]["verified"] is False


def test_enum_чтение_число_при_цели_имя_не_подтвердилось(rig):
    port = make_port(frame_period_s=0.01)
    original = port.get_param
    port.get_param = lambda b: 1 if b.key == "TriggerMode" else original(b)
    session = rig.make(port=port, run=[_mode("On")])
    assert session.start(3.0) is True
    assert session.param_errors == {"trigger_mode": "не подтвердилось чтением"}


def test_вызовы_порта_профилей_из_одного_потока_владельца_включая_reopen(rig):
    session = rig.make(
        run=_chain(40),
        rest=[_mode("On"), _source("Line0")],
        neter_after_stop=True,
        capabilities=NO_RESTART_REGRAB,
    )
    assert rig.cycle(session) is True
    calls = list(rig.port.calls)
    assert [c for c in calls if c[0] == "open"].__len__() == 2  # старт + reopen
    thread_ids = {c[2] for c in calls}
    assert len(thread_ids) == 1
    assert threading.get_ident() not in thread_ids


def test_значение_рецепта_не_в_param_errors_и_не_в_ERROR(rig, session_log):
    port = make_port(frame_period_s=0.01)
    _refuse(port, "TriggerSelfTriggerPeriod", "range")
    session = rig.make(port=port, run=_chain(987654))
    assert session.start(3.0) is True
    assert session.param_errors == {"trigger_period_ms": "range"}
    assert "987654" not in session.param_errors["trigger_period_ms"]
    assert "987654" not in (session.last_error or "")
    errors = [r for r in session_log.records if r.levelno >= logging.ERROR]
    assert not [r for r in errors if "987654" in r.getMessage()]


def test_без_read_back_и_запись_упала_param_errors_kind(rig):
    port = make_port(frame_period_s=0.01, capabilities=NO_READ_BACK)
    _refuse(port, "TriggerMode", "access")
    session = rig.make(port=port, run=[_mode("On")])
    assert session.start(3.0) is True
    assert session.param_errors == {"trigger_mode": "access"}
    assert session.errors == 1
    assert not [n for n in _names(port) if n.startswith("get_param")]


def test_apply_step_очищает_ошибку_и_статус_своего_поля():
    port = make_port()
    port.open(DeviceIdentity("serial", "FAKE-0001"))
    state = ProfileState()
    runner = ProfileRunner(port, None, state, logging.getLogger(SESSION_LOGGER))
    refusing = {"on": True}
    original = port.set_param

    def set_param(b, value):
        if refusing["on"]:
            raise PortError("access", "set_param")
        return original(b, value)

    port.set_param = set_param
    runner.apply_step(_mode("On"))
    assert state.errors == {"trigger_mode": "access"}
    assert state.node_errors == 1
    refusing["on"] = False
    runner.apply_step(_mode("On"))
    assert state.errors == {}  # ошибка и статус поля убраны в начале шага
    assert state.status["trigger_mode"] == {"verified": True, "rc": None}
    assert state.node_errors == 1  # счётчик не откатывается


def test_состояние_error_rest_не_выполняется(rig):
    session = rig.make(get_frame_errors=3, rest=[_mode("On"), _source("Line0")])
    session.start(3.0)
    _await(lambda: "release" in _names(rig.port), "владелец закрыл порт")
    assert session.state == "error"
    assert not [n for n in _names(rig.port) if n.startswith("set_param")]


def test_reopen_open_упал_close_не_зовётся_errors_плюс_1(rig):
    session = rig.make(rest=[_mode("On")], capabilities=NO_RESTART_REGRAB)
    port = rig.port
    original = port.open
    opens = {"n": 0}

    def flaky_open(ident):
        opens["n"] += 1
        if opens["n"] == 2:
            port._record("open", (ident.kind, ident.value))
            raise PortError("network", "open")
        return original(ident)

    port.open = flaky_open
    assert rig.cycle(session) is True
    names = _names(port)
    assert names.count("close") == 1  # первый close ветки; итоговый после неудавшегося open не зовётся
    assert not [n for n in names if n.startswith("set_param")]
    assert session.errors == 1
    assert names[-1] == "release"


def test_skip_шаг_не_пишется_и_пишет_INFO(rig, session_log):
    session = rig.make(run=[_mode("Off"), _source(None, skip="не нужен: trigger_mode=Off")])
    assert session.start(3.0) is True
    assert not [n for n in _names(rig.port) if n.startswith("set_param(TriggerSource")]
    infos = [
        r
        for r in session_log.records
        if r.name == SESSION_LOGGER and "skip=не нужен: trigger_mode=Off" in r.getMessage()
    ]
    assert infos


def test_on_timing_apply_по_каждому_полю(rig):
    session = rig.make(run=_chain(40))
    assert session.start(3.0) is True
    applies = [t for t in rig.timings if t[0] == "apply"]
    assert len(applies) == 3
    assert all(seconds >= 0 for _, seconds in applies)


def test_сторож_видит_зависший_set_param_профиля(rig):
    port = make_port(frame_period_s=0.01)
    original = port.set_param
    port.set_param = lambda b, value: (time.sleep(0.8), original(b, value))[1]
    session = rig.make(port=port, run=[_mode("On")], timeout_ms=100, watchdog_s=0.5)
    assert session.start(3.0) is True
    assert [name for name, _ in rig.stalls] == ["set_param"]  # ровно один on_stall на вызов
    assert rig.stalls[0][1] >= 0.5


def test_сторож_видит_open_ветки_reopen(rig):
    session = rig.make(
        rest=[_mode("On")], open_delay_s=0.8, capabilities=NO_RESTART_REGRAB, timeout_ms=100, watchdog_s=0.5
    )
    assert rig.cycle(session) is True
    assert [name for name, _ in rig.stalls].count("open") == 2  # open старта и open reopen
    assert all(seconds >= 0.5 for _, seconds in rig.stalls)


def test_start_сбрасывает_params_status_params_и_ошибки_прошлого_цикла(rig):
    """Ловит инъекцию «в ProfileState.reset убран status.clear()» (и params.clear / errors.clear).

    Один сеанс, два цикла: rest первого цикла пишет `exposure_time`, которого нет в run. Без сброса на втором
    `start()` статус/значение этого поля пережило бы начало нового run.
    """
    exposure = Step("exposure_time", Binding("genicam", "ExposureTime", "float"), 900.0, None, None)
    session = rig.make(run=[_mode("On")], rest=[exposure])
    assert rig.cycle(session) is True
    assert sorted(session.params_status) == ["exposure_time", "trigger_mode"]  # rest дописал
    _await(lambda: not session.device_held, "владелец первого цикла вышел")

    assert session.start(3.0) is True
    assert sorted(session.params_status) == ["trigger_mode"]  # начало run сбросило прошлый цикл
    assert sorted(session.params) == ["trigger_mode"]
    assert session.param_errors == {}
