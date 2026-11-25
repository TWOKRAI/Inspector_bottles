# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты потери связи с камерой и переподключения (W2-a, W2-a1; RED до кода; автор — тестер).

Purpose:
    Закрепить до реализации контракт сеанса `DeviceSession` (параметры `reconnect`, `link_silence_s`,
    `reconnect_interval_s`; состояние `lost`; `link()`; `reconnecting`; строки лога `camera_device.session`)
    и контракт плагина камеры (поля register'а, ключ `link` в state, health, причина готовности).

Источник — только DESIGN брифа `tasks/W2-a.tester.md`; код реализации и фейка не читался. Ожидаемые значения —
литералы. Порт — фейк (`Services.camera_device.testing.fake_port`); сеанс, плагин, `WorkerManager`, `HealthState`,
`TreeStore`, `StateProxy` — настоящие. Вызов, который может зависнуть, идёт в daemon-потоке с дедлайном `join`;
ожидание — опрос с дедлайном 5 с. Импорты тестируемых классов — внутри тестов и помощников: отсутствие сущности
роняет тест, а не сбор файла.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from multiprocess_framework.modules.process_module.health import get_or_create_health_state
from multiprocess_framework.modules.process_module.heartbeat.telemetry import PluginLevels
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore
from multiprocess_framework.modules.state_store_module.proxy.state_proxy import StateProxy
from multiprocess_framework.modules.worker_module import WorkerManager

__all__ = []

_WAIT_S = 5.0
_SESSION_LOGGER = "camera_device.session"
_LOST_PREFIX = "session: связь с прибором потеряна ("
_LOST_SUFFIX = "); переподключение каждые 0.5 с"
_RECOVERED_PREFIX = "session: связь восстановлена за "
_RECOVERED_PART = ", попыток "
_PROCESS = "cam_link"
_TREE_PATH = "processes.cam_link.state.plugins.camera_device"
_RECONNECT = {"reconnect": True, "link_silence_s": 0.5, "reconnect_interval_s": 0.5}
_PLUGIN_CFG = {
    "auto_start": False,
    "camera_id": 3,
    "device_select": "serial",
    "device_serial": "FAKE-0001",
    "timeout_ms": 100,
    "reconnect": True,
    "link_silence_s": 0.5,
    "reconnect_interval_s": 0.5,
}


# ---------------------------------------------------------------------------------------------- #
# Помощники
# ---------------------------------------------------------------------------------------------- #


def _call(fn: Callable[[], Any], deadline: float = 8.0) -> Any:
    """Вызвать `fn` в daemon-потоке; не вернулся за `deadline` — тест падает; исключение пробрасывается."""
    box: dict[str, Any] = {}

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


def _await(
    pred: Callable[[], bool],
    message: str,
    deadline: float = _WAIT_S,
    *,
    pump: Callable[[], Any] | None = None,
    seen: Callable[[], Any] | None = None,
) -> None:
    """Опрос условия до дедлайна; `pump` крутится перед каждым опросом, `seen` — что показать при отказе."""
    end = time.monotonic() + deadline
    while True:
        if pump is not None:
            pump()
        if pred():
            return
        if time.monotonic() >= end:
            break
        time.sleep(0.005)
    observed = f"; наблюдалось: {seen()!r}" if seen is not None else ""
    pytest.fail(f"не дождались за {deadline} с: {message}{observed}")


class _Opens:
    """Обёртка над `port.open`: все попытки и успешные (с длиной журнала порта в момент успеха)."""

    def __init__(self, port: Any) -> None:
        self.attempts = 0
        self.ok_marks: list[int] = []
        original = port.open

        def counted_open(*args: Any, **kwargs: Any) -> Any:
            self.attempts += 1
            result = original(*args, **kwargs)
            self.ok_marks.append(len(port.calls))  # всё, что в журнале дальше, записано после этого open
            return result

        port.open = counted_open


def _plan(trigger: str | None = None, exposure: float | None = None) -> tuple:
    """Непустой план из настоящих `Step` с привязками фейка; `run[0].binding` — узел пробы."""
    from Services.camera_device.params import Step
    from Services.camera_device.testing.fake_port import FAKE_BINDINGS

    steps = []
    if trigger is not None:
        steps.append(Step("trigger_mode", FAKE_BINDINGS["trigger_mode"], trigger))
    if exposure is not None:
        steps.append(Step("exposure_time", FAKE_BINDINGS["exposure_time"], exposure))
    return tuple(steps)


class _Rig:
    """Настоящие `DeviceSession` + `WorkerManager` над фейк-портом; копит переходы состояний и кадры."""

    def __init__(self) -> None:
        self.wm = WorkerManager("test_cam_link")
        self.sessions: list[Any] = []
        self.states: list[str] = []  # новые состояния в порядке вызовов on_state
        self.frames: list[Any] = []

    def port(self, *, events: bool = False, **opts: Any) -> tuple[Any, _Opens]:
        from Services.camera_device.testing import fake_port

        opts.setdefault("frame_period_s", 0.01)
        factory = fake_port.make_link_event_port if events else fake_port.make_port
        port = factory(**opts)
        return port, _Opens(port)

    def session(self, port: Any, *, run: tuple, **kwargs: Any) -> Any:
        from Services.camera_device.session import DeviceSession

        session = DeviceSession(
            port,
            port.sdk,
            None,
            timeout_ms=100,
            watchdog_s=5.0,
            on_frame=self.frames.append,
            on_state=lambda old, new: self.states.append(new),
            workers=self.wm,
            worker_prefix=f"camera_device_link_{len(self.sessions)}",
            run=run,
            **kwargs,
        )
        self.sessions.append(session)
        return session

    def start(self, session: Any) -> bool:
        return _call(lambda: session.start(5.0))

    def grab(self, session: Any) -> None:
        """Запустить и дождаться настоящего захвата: состояние `grabbing` и хотя бы два кадра."""
        assert self.start(session) is True
        _await(
            lambda: session.state == "grabbing" and len(self.frames) >= 2,
            "grabbing и кадры до обрыва",
            seen=lambda: (session.state, len(self.frames)),
        )

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
    """Записи логгера `camera_device.session` (свой обработчик: не зависит от propagate и чужих мостов)."""
    records: list[logging.LogRecord] = []

    class _Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger(_SESSION_LOGGER)
    handler = _Collect(level=logging.DEBUG)
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    yield records
    logger.removeHandler(handler)
    logger.setLevel(old_level)


def _lines(records: list[logging.LogRecord], level: int, prefix: str) -> list[str]:
    return [r.getMessage() for r in list(records) if r.levelno == level and r.getMessage().startswith(prefix)]


def _link(session: Any) -> dict:
    return _call(session.link, 2.0)


# ---------------------------------------------------------------------------------------------- #
# Сеанс
# ---------------------------------------------------------------------------------------------- #


def test_disconnect_event_marks_lost_then_reconnects(rig):
    """Одно событие прибора `disconnected` (без `disconnect()`) -> `lost`, `outages` 1, второй `open`, `grabbing`.

    `link_silence_s 0` и кадры идут: потерю может дать только событие.
    """
    port, opens = rig.port(events=True)
    session = rig.session(port, run=_plan("Off"), reconnect=True, link_silence_s=0.0, reconnect_interval_s=0.5)
    rig.grab(session)
    assert "lost" not in rig.states
    assert len(opens.ok_marks) == 1

    port.emit_link_event("disconnected")
    _await(lambda: "lost" in rig.states, "переход в lost по событию прибора", seen=lambda: list(rig.states))
    assert _link(session)["outages"] == 1

    _await(
        lambda: len(opens.ok_marks) >= 2 and session.state == "grabbing",
        "второй open и grabbing",
        seen=lambda: (opens.attempts, session.state),
    )
    _await(lambda: _link(session)["state"] == "up", "link.state == up", seen=lambda: _link(session))
    assert _link(session)["outages"] == 1


def test_free_run_silence_is_lost_even_if_probe_answers(rig, logs):
    """Свободный поток (`trigger_mode Off`) молчит, `get_param` отвечает -> `lost` не позже 3 с, одна WARNING."""
    port, _opens = rig.port(frame_period_s=60)
    session = rig.session(port, run=_plan("Off"), **_RECONNECT)
    assert rig.start(session) is True

    _await(lambda: "lost" in rig.states, "lost по тишине свободного потока", 3.0, seen=lambda: list(rig.states))
    time.sleep(1.0)  # ещё минимум один цикл переподключения: вторая WARNING появиться не должна

    warnings = _lines(logs, logging.WARNING, _LOST_PREFIX)
    assert len(warnings) == 1, warnings
    assert warnings[0].endswith(_LOST_SUFFIX), warnings[0]


def test_hw_trigger_silence_with_answering_probe_is_idle(rig, logs):
    """Аппаратный триггер (`trigger_mode On`) молчит, проба отвечает -> `grabbing`, `link.state == idle`."""
    port, opens = rig.port(frame_period_s=60)
    session = rig.session(port, run=_plan("On"), **_RECONNECT)
    assert rig.start(session) is True

    time.sleep(2.0)  # четыре срока `link_silence_s`

    assert session.state == "grabbing"
    assert _link(session)["state"] == "idle"
    assert "lost" not in rig.states
    assert opens.attempts == 1
    # положительный контроль: обработчик действительно видит строки сеанса, иначе «WARNING нет» пусто
    assert any(r.getMessage().startswith("session state=opening->grabbing") for r in list(logs))
    assert _lines(logs, logging.WARNING, _LOST_PREFIX) == []


def test_recovery_requires_reopen_and_logs_info_once(rig, logs):
    """`disconnect()` -> `lost`; `restore()` -> новый `open`, кадры, `last_error None`, `up`, одна INFO."""
    port, opens = rig.port()
    session = rig.session(port, run=_plan("Off"), **_RECONNECT)
    rig.grab(session)

    port.disconnect()
    _await(lambda: session.state == "lost", "lost после disconnect()", seen=lambda: session.state)
    assert len(opens.ok_marks) == 1
    frames_at_restore = len(rig.frames)
    port.restore()

    _await(lambda: len(opens.ok_marks) >= 2, "второй успешный open после restore()", seen=lambda: opens.attempts)
    _await(lambda: session.state == "grabbing", "grabbing после переоткрытия", seen=lambda: session.state)
    _await(
        lambda: len(rig.frames) >= frames_at_restore + 3,
        "кадры снова идут",
        seen=lambda: len(rig.frames) - frames_at_restore,
    )
    _await(lambda: _link(session)["state"] == "up", "link.state == up", seen=lambda: _link(session))
    time.sleep(1.0)  # повтор INFO за этот срок был бы виден

    assert session.last_error is None
    infos = _lines(logs, logging.INFO, _RECOVERED_PREFIX)
    assert len(infos) == 1, infos
    assert _RECOVERED_PART in infos[0], infos[0]
    assert port.max_open_handles == 1  # прежний сеанс прибора закрыт до нового open


def test_lost_holds_until_grabbing(rig):
    """Прибор отсутствует 2 с, повторы падают `not_found` -> всё это время `lost`, `attempts >= 2`."""
    port, _opens = rig.port()
    session = rig.session(port, run=_plan("Off"), **_RECONNECT)
    rig.grab(session)

    port.disconnect()
    _await(lambda: "lost" in rig.states, "lost после disconnect()", seen=lambda: list(rig.states))
    lost_index = rig.states.index("lost")
    sampled = []
    for _ in range(20):
        time.sleep(0.1)
        sampled.append(session.state)

    assert sampled == ["lost"] * 20
    assert rig.states[lost_index:] == ["lost"], "между опросами было другое состояние"
    assert "not_found" in (session.last_error or ""), session.last_error
    assert _link(session)["attempts"] >= 2


def test_stop_during_backoff_returns_promptly(rig):
    """Пауза между попытками 10 с: `stop(2.0)` из `lost` возвращается быстрее 2 с и гасит цикл."""
    port, opens = rig.port()
    session = rig.session(port, run=_plan("Off"), reconnect=True, link_silence_s=0.5, reconnect_interval_s=10.0)
    rig.grab(session)
    port.disconnect()
    _await(lambda: session.state == "lost", "lost после disconnect()", seen=lambda: session.state)
    time.sleep(0.5)  # владелец уже стоит в паузе 10 с

    t0 = time.perf_counter()
    _call(lambda: session.stop(2.0))
    seconds = time.perf_counter() - t0

    assert seconds < 2.0
    assert session.device_held is False
    assert session.state == "closed"
    attempts = opens.attempts
    time.sleep(1.0)
    assert opens.attempts == attempts


def test_stop_after_failed_busy_attempt_ends_loop(rig):
    """Прибор занят 60 с: после хотя бы одного повтора `stop()` -> `closed`, нового `open` нет."""
    port, opens = rig.port(busy_for_s=60)
    session = rig.session(port, run=_plan("Off"), **_RECONNECT)
    assert rig.start(session) is False
    _await(lambda: opens.attempts >= 2, "повтор open после отказа busy", seen=lambda: opens.attempts)

    _call(lambda: session.stop(2.0))

    assert session.state == "closed"
    assert session.device_held is False
    attempts = opens.attempts
    time.sleep(1.0)  # при цикле было бы около двух новых попыток
    assert opens.attempts == attempts


def test_reconnect_off_free_run_silence_is_error(rig, logs):
    """`reconnect False`: кадры шли и прекратились -> `error`, `link.state == lost`, одна ERROR, без `open`.

    Кадры глушит обёртка над `get_frame` (`None` = кадра нет): проба `get_param` при этом отвечает, потерю
    даёт только правило тишины свободного потока.
    """
    port, opens = rig.port()
    silent = threading.Event()
    original_get_frame = port.get_frame

    def get_frame(*args: Any, **kwargs: Any) -> Any:
        if silent.is_set():
            time.sleep(0.1)  # срок кадра сеанса, timeout_ms 100
            return None
        return original_get_frame(*args, **kwargs)

    port.get_frame = get_frame
    session = rig.session(port, run=_plan("Off"), reconnect=False, link_silence_s=0.5, reconnect_interval_s=0.5)
    rig.grab(session)

    silent.set()
    _await(lambda: session.state == "error", "state == error", seen=lambda: session.state)

    assert _link(session)["state"] == "lost"
    assert session.last_error
    assert session.reconnecting is False
    time.sleep(2.0)
    assert opens.attempts == 1
    errors = _lines(logs, logging.ERROR, _LOST_PREFIX)
    assert len(errors) == 1, errors


def test_free_run_reopen_without_frames_stays_lost(rig, logs):
    """Переоткрытие удаётся, кадров нет: 3 x `link_silence_s` состояние не `grabbing`, WARNING одна."""
    port, opens = rig.port(frame_period_s=60)
    session = rig.session(port, run=_plan("Off"), **_RECONNECT)
    assert rig.start(session) is True
    _await(lambda: "lost" in rig.states, "lost по тишине", seen=lambda: list(rig.states))
    lost_index = rig.states.index("lost")

    sampled = set()
    end = time.monotonic() + 1.5  # 3 x link_silence_s 0.5
    while time.monotonic() < end:
        sampled.add(session.state)
        time.sleep(0.02)

    assert "grabbing" not in sampled, sampled
    assert "grabbing" not in rig.states[lost_index:], rig.states
    assert len(opens.ok_marks) >= 2, "переоткрытия не было: окно ничего не проверило"
    assert len(_lines(logs, logging.WARNING, _LOST_PREFIX)) == 1
    assert _lines(logs, logging.INFO, _RECOVERED_PREFIX) == []


def test_busy_at_start_retries_until_free(rig):
    """Занят 1 с: `start()` -> `False` при `reconnecting True`, затем `grabbing`, открытий не меньше 2."""
    port, opens = rig.port(busy_for_s=1.0)
    session = rig.session(port, run=_plan("Off"), **_RECONNECT)

    ok = rig.start(session)
    reconnecting = session.reconnecting

    assert ok is False
    assert reconnecting is True
    _await(lambda: session.state == "grabbing", "grabbing после освобождения", seen=lambda: session.state)
    _await(lambda: len(rig.frames) >= 1, "первый кадр после освобождения")
    assert opens.attempts >= 2


def test_write_during_outage_reaches_reopened_device(rig):
    """Правка `ExposureTime 5000` во время `lost` доходит до прибора после второго `open`."""
    from Services.camera_device.params import Step
    from Services.camera_device.testing.fake_port import FAKE_BINDINGS

    port, opens = rig.port()
    session = rig.session(port, run=_plan("Off", exposure=1000.0), **_RECONNECT)
    rig.grab(session)
    port.disconnect()
    _await(lambda: session.state == "lost", "lost после disconnect()", seen=lambda: session.state)

    edit = [Step("exposure_time", FAKE_BINDINGS["exposure_time"], 5000)]
    _call(lambda: session.apply(edit, "restart"))
    time.sleep(0.3)  # владелец успевает разобрать правку, пока прибора нет
    port.restore()
    _await(lambda: len(opens.ok_marks) >= 2, "второй успешный open", seen=lambda: opens.attempts)

    def exposure_writes_after_reopen() -> list:
        tail = list(port.calls)[opens.ok_marks[1] :]
        return [args[1] for name, args, _tid in tail if name == "set_param" and args[0] == "ExposureTime"]

    _await(
        lambda: 5000 in exposure_writes_after_reopen(),
        "запись ExposureTime 5000 после второго open",
        seen=exposure_writes_after_reopen,
    )
    time.sleep(0.5)
    assert exposure_writes_after_reopen()[-1] == 5000, "старое значение плана записано поверх правки"


def test_reconnect_off_keeps_terminal_error(rig):
    """ОХРАННЫЙ (зелёный до кода): без новых параметров три ошибки кадра -> `error`, нового `open` нет."""
    port, opens = rig.port(get_frame_errors=3)
    session = rig.session(port, run=_plan("Off"))
    rig.start(session)
    _await(lambda: session.state == "error", "state == error после трёх ошибок кадра", seen=lambda: session.state)

    time.sleep(2.0)

    assert session.state == "error"
    assert opens.attempts == 1


# ---------------------------------------------------------------------------------------------- #
# Плагин
# ---------------------------------------------------------------------------------------------- #


class _TreeRouter:
    """Приёмник сообщений настоящего `StateProxy`: складывает `merge`/`delete` в настоящее дерево."""

    def __init__(self, store: TreeStore) -> None:
        self.store = store

    def send_async(self, msg: dict, priority: str = "normal") -> None:
        data = msg["data"]
        if msg["command"] == "state.merge":
            self.store.merge(data["path"], data["data"])
        elif msg["command"] == "state.delete":
            self.store.delete(data["path"])


class _PluginRig:
    """Настоящий плагин камеры + настоящий сеанс над фейком; настоящие health, дерево состояния и уровни."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, port: Any, cfg: dict) -> None:
        from Services.camera_device import plugin_base
        from Services.camera_device.plugin_base import CameraDevicePlugin

        monkeypatch.setattr(plugin_base, "create_port", lambda driver: port)
        monkeypatch.setattr(plugin_base, "_TICK_S", 0.0)  # каждый produce() сверяет события
        self.services = MockProcessServices(name=_PROCESS, config=cfg, plugin_levels=PluginLevels())
        self.wm = WorkerManager("test_cam_link_plugin")
        self.services.worker_manager = self.wm
        self.ctx = PluginContext(services=self.services, config=cfg, plugin_name="camera_device")
        self.tree = TreeStore()
        self.ctx.state_proxy = StateProxy(_PROCESS, router=_TreeRouter(self.tree))
        self.plugin = CameraDevicePlugin()
        self.plugin.configure(self.ctx)

    def take(self) -> dict:
        return _call(lambda: self.plugin.cmd_take_device({}))

    def state(self) -> str:
        return _call(lambda: self.plugin.cmd_get_status({}))["state"]

    def readiness(self) -> list:
        return _call(lambda: self.plugin.readiness(self.ctx), 2.0)

    def link_state(self) -> str | None:
        node = self.tree.get(_TREE_PATH, None) or {}
        link = node.get("link")
        return link.get("state") if isinstance(link, dict) else None

    def health(self) -> str:
        return get_or_create_health_state(self.services).snapshot()["status"]

    def wait(self, pred: Callable[[], bool], message: str) -> None:
        """Ждать, ведя `produce()` как процесс-источник."""
        _await(
            pred,
            message,
            pump=lambda: _call(self.plugin.produce, 2.0),
            seen=lambda: {"state": self.state(), "link.state": self.link_state(), "health": self.health()},
        )

    def close(self) -> None:
        try:
            if getattr(self.plugin, "_session", None) is not None:
                _call(lambda: self.plugin.shutdown(self.ctx), 10.0)
        finally:
            self.wm.stop_all_workers(2.0)


@pytest.fixture
def make_plugin(monkeypatch):
    rigs: list[_PluginRig] = []

    def factory(port: Any, **cfg_extra: Any) -> _PluginRig:
        built = _PluginRig(monkeypatch, port, {**_PLUGIN_CFG, **cfg_extra})
        rigs.append(built)
        return built

    yield factory
    for built in rigs:
        built.close()


def test_plugin_lost_readiness_is_failure_literal(make_plugin):
    """При `lost` готовность — ровно одна причина `failure`.

    План по умолчанию (`trigger_managed False`): шага `trigger_mode` нет, тишину решает проба.
    """
    from Services.camera_device.testing.fake_port import make_port

    port = make_port(frame_period_s=0.01)
    rig = make_plugin(port)
    assert rig.take()["status"] == "ok"
    assert rig.readiness() == []

    port.disconnect()
    rig.wait(lambda: rig.state() == "lost", "сеанс плагина в lost")

    assert rig.readiness() == [{"severity": "failure", "reason": "связь с камерой потеряна, переподключение"}]


def test_plugin_publishes_link_and_degrades_on_loss(make_plugin):
    """State плагина несёт `link`; потеря -> `link.state lost` и health `degraded`, возврат -> `up` и `ok`."""
    from Services.camera_device.testing.fake_port import make_port

    port = make_port(frame_period_s=0.01)
    rig = make_plugin(port, trigger_managed=True, trigger_mode="Off")
    assert rig.take()["status"] == "ok"
    rig.wait(lambda: rig.link_state() == "up", "link.state == up после старта")
    assert rig.health() == "ok"

    port.disconnect()
    rig.wait(lambda: rig.link_state() == "lost", "link.state == lost после обрыва")
    rig.wait(lambda: rig.health() == "degraded", "health degraded при lost")

    port.restore()
    rig.wait(lambda: rig.link_state() == "up", "link.state == up после возврата")
    rig.wait(lambda: rig.health() == "ok", "health ok после возврата")


def test_plugin_register_defaults():
    """Поля register'а и их умолчания: `reconnect False`, тишина 3.0 с, пауза попыток 2.0 с."""
    from Services.camera_device.registers_base import CameraDeviceRegisters

    registers = CameraDeviceRegisters()

    assert registers.reconnect is False
    assert registers.link_silence_s == 3.0
    assert registers.reconnect_interval_s == 2.0
