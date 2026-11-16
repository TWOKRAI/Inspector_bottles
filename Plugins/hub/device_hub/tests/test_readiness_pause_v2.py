"""Слепая приёмка Task 2.2a2, срез S4b «плагин»: готовность по свежести связи и пауза (RED 6-10).

Purpose:
    Контракт ``DeviceHubPlugin.readiness`` / ``pause`` / ``resume`` / ``_set_conn`` через настоящий плагин на
    ``make_ctx``. Устройства рецепта (``recipe_devices``) подключаются разбором очереди плагина, драйверы — двойники
    наследника ``FakeDriver`` (внедряются публичной ``register_driver_factory``). Воркер устройства ``dev_<id>``
    запускается руками в daemon-потоке (``FakeWorkerManager`` сам воркеры не гонит). Зависающий или пошаговый ``tick`` —
    ``threading.Event`` / ``Semaphore`` теста (пермит = тик); на ``poll_interval_s`` по времени тест не опирается.
    Часы плагина подменяются ``monkeypatch.setattr(plugin_mod, "_clock", ...)``; срок паузы их не использует.
    Любой вызов, который может повиснуть, идёт в daemon-потоке с join-дедлайном. Ожидаемые значения — литералы.

Public API:
    Только тесты ``test_<пункт>_*``: ``test_r6*`` - свежесть по успешному тику, ``test_r7*`` - порог выключен или
    негоден, ``test_r8*`` - исключения тика, ``test_r9*`` - пауза, ``test_r10*`` - единственный писатель и бюджет.

Stability: lite
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from Plugins.hub.device_hub.plugin import DeviceHubPlugin
from Plugins.hub.device_hub.tests.conftest import make_ctx
from Plugins.hub.device_hub.tests.test_spi_commands_acceptance import Calls, FakeDriver

_CALL_S = 8.0  # дедлайн любого вызова, который может повиснуть
_STEP_S = 0.02  # период опроса
_DEV = "robot_main"
_STALE_FAIL = [{"severity": "failure", "reason": "robot_main: нет обновления связи"}]
_LINK_ERROR = [{"severity": "failure", "reason": "robot_main: ошибка связи"}]
_NOT_CONNECTED = [{"severity": "failure", "reason": "robot_main не подключено"}]
_TCP = {"type": "tcp", "host": "127.0.0.1", "port": 50999, "unit_id": 2}
_BRIDGE = {"type": "bridge", "bridge": "r_v2"}


# --------------------------------------------------------------------------------------------------
# Ожидание и ограниченные вызовы
# --------------------------------------------------------------------------------------------------


def bounded(fn: Callable[[], Any], deadline_s: float = _CALL_S) -> Any:
    """Вызов в daemon-потоке с join-дедлайном; ошибка потока поднимается в тесте, зависание — ``AssertionError``."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — переносится в поток теста
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True, name="s4b-bounded")
    thread.start()
    thread.join(deadline_s)
    assert not thread.is_alive(), f"вызов завис дольше {deadline_s} с"
    if "error" in box:
        raise box["error"]
    return box.get("result")


def until(pred: Callable[[], Any], deadline_s: float, what: str) -> float:
    """Ждать, пока ``pred()`` истинно (опрос с дедлайном); вернуть, сколько секунд ждали."""
    t0 = time.monotonic()
    while True:
        if pred():
            return time.monotonic() - t0
        if time.monotonic() - t0 > deadline_s:
            raise AssertionError(f"не дождались за {deadline_s} с: {what}")
        time.sleep(_STEP_S)


# --------------------------------------------------------------------------------------------------
# Управление тиком двойника
# --------------------------------------------------------------------------------------------------


class Hang:
    """Тик висит, пока тест не вызовет ``release()``; после отпускания все тики здоровые."""

    def __init__(self) -> None:
        self.gate = threading.Event()

    def __call__(self) -> None:
        self.gate.wait(30.0)

    def release(self) -> None:
        self.gate.set()

    def close(self) -> None:
        self.gate.set()


class Steps:
    """Пошаговый тик: один ``permit`` = один тик; итог тика — по списку (``"raise"`` бросает, иное — штатный)."""

    def __init__(self, outcomes: list[str]) -> None:
        self.outcomes = list(outcomes)
        self.permits = threading.Semaphore(0)
        self.cond = threading.Condition()
        self.started = 0
        self.finished = 0

    def __call__(self) -> None:
        with self.cond:
            self.started += 1
            self.cond.notify_all()
        if not self.permits.acquire(timeout=30.0):
            return
        outcome = self.outcomes.pop(0) if self.outcomes else "ok"
        with self.cond:
            self.finished += 1
            self.cond.notify_all()
        if outcome == "raise":
            raise RuntimeError("tick boom")

    def wait_first_entry(self, deadline_s: float = 5.0) -> None:
        until(lambda: self.started >= 1, deadline_s, "воркер вошёл в первый тик")

    def step(self, deadline_s: float = 5.0) -> None:
        """Разрешить один тик и дождаться, пока воркер отработал его итог и вошёл в следующий тик."""
        target = self.finished + 1
        self.permits.release()
        until(lambda: self.finished >= target and self.started >= target + 1, deadline_s, f"тик {target} отработан")

    def close(self) -> None:
        self.permits.release(1000)


# --------------------------------------------------------------------------------------------------
# Двойники драйверов
# --------------------------------------------------------------------------------------------------


class Double(FakeDriver):
    """Двойник: пишет приход команд, умеет медленную команду, зависающий тик, исключение чтения ``is_connected``."""

    kind = "robot"
    pause_action = ("stop", {"level": "SOFT"})

    def __init__(self, entry: Any, protocol: Any = None, *, calls: Calls | None = None) -> None:
        super().__init__(entry, protocol, calls=calls)
        self.tick_hook: Callable[[], None] | None = None
        self.tick_count = 0
        self.conn_raises = False
        self.connect_ok = True
        self.cmd_delay_s = 0.0
        self.cmd_gate = threading.Event()  # открывается в уборке: медленные команды не держат потоки
        self.arrivals: list[tuple[str, dict, float]] = []
        self.arrivals_guard = threading.Lock()

    def connect(self) -> bool:
        if not self.connect_ok:
            self.up = False
            return False
        return super().connect()

    @property
    def is_connected(self) -> bool:
        if self.conn_raises:
            raise RuntimeError("is_connected boom")
        return self.up

    def tick(self, stop_event: Any = None) -> None:
        self.tick_count += 1
        hook = self.tick_hook
        if hook is not None:
            hook()
        return None

    def call(self, op: str, args: dict) -> dict:
        with self.arrivals_guard:
            self.arrivals.append((op, dict(args), time.monotonic()))
        if self.cmd_delay_s > 0:
            self.cmd_gate.wait(self.cmd_delay_s)
        return super().call(op, args)

    def stops(self) -> list[tuple[str, dict, float]]:
        """Приходы команд паузы (``stop`` / ``abort``)."""
        with self.arrivals_guard:
            return [a for a in self.arrivals if a[0] in ("stop", "abort")]

    def commands(self) -> int:
        with self.arrivals_guard:
            return len(self.arrivals)


class RobotV2(Double):
    kind = "robot"
    pause_action = ("stop", {"level": "SOFT"})


class RobotV1(Double):
    kind = "robot"
    pause_action = ("abort", {"mode": 3})


class Belt(Double):
    kind = "vfd"
    pause_action = ("stop", {})


_CLASS_BY_PROTOCOL: dict[str, type[Double]] = {"delta_v2": RobotV2, "delta_universal3": RobotV1, "gd20_bridge": Belt}

# устройства рецепта по умолчанию: (id, kind, protocol, transport)
_ROBOT_ONLY = [(_DEV, "robot", "delta_v2", _TCP)]
_THREE = [
    ("r_v2", "robot", "delta_v2", _TCP),
    ("r_v1", "robot", "delta_universal3", _TCP),
    ("belt", "vfd", "gd20_bridge", _BRIDGE),
]


# --------------------------------------------------------------------------------------------------
# Часы плагина
# --------------------------------------------------------------------------------------------------


class Clock:
    """Подмена ``Plugins.hub.device_hub.plugin._clock``: настоящие часы плюс сдвиг теста."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import Plugins.hub.device_hub.plugin as plugin_mod

        real = getattr(plugin_mod, "_clock")  # до S4b имени нет: красный с AttributeError
        self.offset = 0.0
        monkeypatch.setattr(plugin_mod, "_clock", lambda *a, **k: real(*a, **k) + self.offset)

    def jump(self, seconds: float) -> None:
        self.offset += seconds


# --------------------------------------------------------------------------------------------------
# Сцена: плагин + двойники + воркеры
# --------------------------------------------------------------------------------------------------


@dataclass
class PauseRun:
    t0: float
    t1: float
    error: BaseException | None

    @property
    def elapsed(self) -> float:
        return self.t1 - self.t0


@dataclass
class Scene:
    plugin: DeviceHubPlugin
    ctx: MagicMock
    ids: list[str]
    drivers: dict[str, Double] = field(default_factory=dict)
    clock: Clock | None = None
    threads: list[threading.Thread] = field(default_factory=list)
    stop_events: list[threading.Event] = field(default_factory=list)
    hooks: list[Any] = field(default_factory=list)

    # --- подключение и воркеры ---

    def connect_all(self, dev_ids: list[str] | None = None) -> None:
        """«Подключить» через команду плагина, затем разбор очереди плагина (как супервизор)."""
        targets = dev_ids or list(self.ids)
        for dev_id in targets:
            assert self.plugin.cmd_device_connect({"device_id": dev_id})["status"] == "ok"
        bounded(self.plugin._process_conn_queue)
        for dev_id in targets:
            assert dev_id in self.drivers, f"обвязка: драйвер {dev_id} не создан фабрикой"

    def start_worker(self, dev_id: str = _DEV) -> threading.Thread:
        """``_ensure_device_workers`` и запуск ``dev_<id>`` в daemon-потоке; поток возвращается."""
        bounded(self.plugin._ensure_device_workers)
        workers = self.ctx.worker_manager.workers
        assert f"dev_{dev_id}" in workers, f"обвязка: воркер dev_{dev_id} не создан ({sorted(workers)})"
        fn = workers[f"dev_{dev_id}"]["fn"]
        stop_evt, pause_evt = threading.Event(), threading.Event()
        thread = threading.Thread(target=fn, args=(stop_evt, pause_evt), daemon=True, name=f"s4b-dev-{dev_id}")
        thread.start()
        self.threads.append(thread)
        self.stop_events.append(stop_evt)
        return thread

    def hook(self, dev_id: str, hook: Any) -> Any:
        self.drivers[dev_id].tick_hook = hook
        self.hooks.append(hook)
        return hook

    # --- чтения ---

    def readiness(self) -> list[dict]:
        return self.plugin.readiness(self.ctx)

    def wait_readiness(self, expected: list[dict], deadline_s: float) -> float:
        last: list[Any] = []

        def reached() -> bool:
            last[:] = [self.readiness()]
            return last[0] == expected

        try:
            return until(reached, deadline_s, f"readiness == {expected}")
        except AssertionError as exc:
            raise AssertionError(f"{exc}; последний ответ readiness: {last[0] if last else None}") from None

    def records(self, path: str) -> list[Any]:
        """Записи в хранилище по ``path``: вторые аргументы вызовов ``ctx.state_proxy.set(path, data)``."""
        return [c.args[1] for c in self.ctx.state_proxy.set.call_args_list if len(c.args) >= 2 and c.args[0] == path]

    def last_conn_record(self, dev_id: str = _DEV) -> Any:
        recs = self.records(f"devices.state.{dev_id}.conn")
        return recs[-1] if recs else None

    def scope_incidents(self) -> list[Any]:
        return [c for c in self.ctx.health.report_error.call_args_list if c.kwargs.get("context") == "device_hub.scope"]

    # --- пауза ---

    def pause(self, deadline_s: float = _CALL_S) -> PauseRun:
        box: dict[str, Any] = {}

        def body() -> None:
            box["t0"] = time.monotonic()
            try:
                self.plugin.pause(self.ctx)
            except BaseException as exc:  # noqa: BLE001
                box["error"] = exc
            box["t1"] = time.monotonic()

        thread = threading.Thread(target=body, daemon=True, name="s4b-pause")
        thread.start()
        thread.join(deadline_s)
        assert not thread.is_alive(), f"pause не вернулся за {deadline_s} с"
        return PauseRun(t0=box["t0"], t1=box["t1"], error=box.get("error"))

    def resume(self) -> None:
        bounded(lambda: self.plugin.resume(self.ctx))

    def close(self) -> None:
        for hook in self.hooks:
            hook.close()
        for drv in self.drivers.values():
            drv.cmd_gate.set()
        for evt in self.stop_events:
            evt.set()
        for thread in self.threads:
            thread.join(3.0)


@pytest.fixture
def make_scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Фабрика сцен: ``make_scene(devices, params=..., clock=True)``; уборка отпускает всё зависшее."""
    scenes: list[Scene] = []

    def make(
        devices: list[tuple[str, str, str, dict]] | None = None,
        *,
        params: dict[str, Any] | None = None,
        clock: bool = False,
        connect: bool = True,
    ) -> Scene:
        devices = devices or _ROBOT_ONLY
        registry = tmp_path / "devices.yaml"
        recipe = [
            {
                "id": dev_id,
                "name": dev_id,
                "kind": kind,
                "protocol": protocol,
                "transport": transport,
                "params": dict(params or {}),
            }
            for dev_id, kind, protocol, transport in devices
        ]
        ctx = make_ctx({"registry_path": str(registry), "recipe_devices": recipe}, tmp_registry=registry)
        ctx.health = MagicMock()
        ctx.log_warning = MagicMock()
        fake_clock = Clock(monkeypatch) if clock else None
        plugin = DeviceHubPlugin()
        plugin.configure(ctx)
        scene = Scene(plugin=plugin, ctx=ctx, clock=fake_clock, ids=[d[0] for d in devices])
        scenes.append(scene)

        def build(entry: Any, protocol: Any = None) -> Double:
            drv = _CLASS_BY_PROTOCOL[entry.protocol](entry, protocol)
            scene.drivers[entry.id] = drv
            return drv

        plugin._manager.register_driver_factory("robot", build)
        plugin._manager.register_driver_factory("vfd", build)
        plugin.start(ctx)
        if connect:
            scene.connect_all()
        return scene

    yield make
    for scene in reversed(scenes):
        scene.close()


# ==================================================================================================
# 6. Возраст по успешному тику
# ==================================================================================================

_FRESH = {"conn_stale_s": 1.0, "poll_interval_s": 0.1}


def test_r6a_hanging_tick_goes_stale_within_deadline(make_scene: Callable[..., Scene]) -> None:
    sc = make_scene(params=_FRESH)
    sc.hook(_DEV, Hang())
    sc.start_worker()
    elapsed = sc.wait_readiness(_STALE_FAIL, 2.5)
    assert elapsed <= 2.5


def test_r6b_set_conn_does_not_refresh_age_while_tick_hangs(make_scene: Callable[..., Scene]) -> None:
    sc = make_scene(params=_FRESH)
    sc.hook(_DEV, Hang())
    sc.start_worker()
    sc.wait_readiness(_STALE_FAIL, 2.5)
    sc.plugin._set_conn(_DEV, "connected")
    t0 = time.monotonic()
    samples: list[list[dict]] = []
    while time.monotonic() - t0 < 0.5:
        samples.append(sc.readiness())
        time.sleep(_STEP_S)
    assert samples and all(s == _STALE_FAIL for s in samples), f"ответы после _set_conn: {samples[-3:]}"


def test_r6c_released_tick_clears_stale(make_scene: Callable[..., Scene]) -> None:
    sc = make_scene(params=_FRESH)
    hang = sc.hook(_DEV, Hang())
    sc.start_worker()
    sc.wait_readiness(_STALE_FAIL, 2.5)
    hang.release()
    elapsed = sc.wait_readiness([], 1.5)
    assert elapsed <= 1.5


def test_r6d_healthy_tick_keeps_ready_for_three_seconds(make_scene: Callable[..., Scene]) -> None:
    sc = make_scene(params=_FRESH)
    sc.start_worker()
    drv = sc.drivers[_DEV]
    until(lambda: drv.tick_count >= 1, 3.0, "первый здоровый тик")
    t0 = time.monotonic()
    samples: list[list[dict]] = []
    while time.monotonic() - t0 < 3.0:
        samples.append(sc.readiness())
        time.sleep(_STEP_S)
    bad = [s for s in samples if s != []]
    assert len(samples) > 50 and not bad, f"из {len(samples)} замеров не пусты {len(bad)}: {bad[:2]}"


# ==================================================================================================
# 7. Порог выключен или негоден
# ==================================================================================================

_ABSENT = object()


def _stale_warnings(sc: Scene) -> list[str]:
    return [str(c) for c in sc.ctx.log_warning.call_args_list if "conn_stale_s" in str(c)]


@pytest.mark.parametrize(
    "value",
    [_ABSENT, 0, None, "abc", True],
    ids=["absent", "zero", "none", "abc", "true"],
)
def test_r7_threshold_off_or_invalid_never_goes_stale(make_scene: Callable[..., Scene], value: Any) -> None:
    params: dict[str, Any] = {"poll_interval_s": 0.05}
    if value is not _ABSENT:
        params["conn_stale_s"] = value
    sc = make_scene(params=params, clock=True)
    drv = sc.drivers[_DEV]
    sc.start_worker()
    until(lambda: drv.tick_count >= 3, 3.0, "три здоровых тика до сдвига часов")
    assert sc.clock is not None
    sc.clock.jump(3600.0)
    seen = drv.tick_count
    until(lambda: drv.tick_count >= seen + 3, 3.0, "три тика после сдвига часов")
    for _ in range(3):
        assert sc.readiness() == []
        time.sleep(0.1)
    if value is not _ABSENT and (value == "abc" or value is True):
        warnings = _stale_warnings(sc)
        assert len(warnings) == 1, f"WARNING по conn_stale_s: {warnings}"


# ==================================================================================================
# 8. Исключения тика (пошаговый тик)
# ==================================================================================================

_STEPWISE = {"poll_interval_s": 0.05}


def _stepwise_scene(make_scene: Callable[..., Scene], outcomes: list[str]) -> tuple[Scene, Steps, threading.Thread]:
    sc = make_scene(params=_STEPWISE)
    steps = sc.hook(_DEV, Steps(outcomes))
    thread = sc.start_worker()
    steps.wait_first_entry()
    return sc, steps, thread


def test_r8a_tick_raises_while_driver_down_reports_not_connected(make_scene: Callable[..., Scene]) -> None:
    sc, steps, _ = _stepwise_scene(make_scene, ["raise"])
    sc.drivers[_DEV].up = False
    steps.permits.release()
    elapsed = sc.wait_readiness(_NOT_CONNECTED, 1.0)
    assert elapsed <= 1.0


def test_r8b_three_consecutive_raises_with_link_up_report_link_error(make_scene: Callable[..., Scene]) -> None:
    sc, steps, _ = _stepwise_scene(make_scene, ["raise", "raise", "raise"])
    assert sc.drivers[_DEV].is_connected is True
    steps.step()
    steps.step()
    assert sc.readiness() == [], "после двух исключений подряд связь ещё не ошибочна"
    steps.permits.release()
    sc.wait_readiness(_LINK_ERROR, 1.5)


def test_r8b_series_raise_raise_ok_raise_raise_stays_ready(make_scene: Callable[..., Scene]) -> None:
    sc, steps, _ = _stepwise_scene(make_scene, ["raise", "raise", "ok", "raise", "raise"])
    for _ in range(5):
        steps.step()
    assert sc.readiness() == [], "серия прервана успешным тиком: подряд меньше трёх"


def test_r8c_first_tick_raises_then_healthy_worker_survives(make_scene: Callable[..., Scene]) -> None:
    sc, steps, thread = _stepwise_scene(make_scene, ["raise", "ok", "ok"])
    steps.step()
    assert thread.is_alive(), "воркер устройства умер от исключения первого тика"
    steps.step()
    steps.step()
    assert thread.is_alive()
    assert sc.readiness() == []


def test_r8d_first_tick_raises_and_is_connected_raises_reports_link_error(make_scene: Callable[..., Scene]) -> None:
    sc, steps, thread = _stepwise_scene(make_scene, ["raise"])
    sc.drivers[_DEV].conn_raises = True
    steps.step()
    sc.wait_readiness(_LINK_ERROR, 1.5)
    assert thread.is_alive(), "воркер устройства умер от исключения чтения is_connected"


# ==================================================================================================
# 9. Пауза
# ==================================================================================================


def _stop_counts(sc: Scene) -> dict[str, int]:
    return {dev_id: len(drv.stops()) for dev_id, drv in sc.drivers.items()}


def test_r9a_slow_robot_does_not_delay_belt_stop(make_scene: Callable[..., Scene]) -> None:
    sc = make_scene(_THREE)
    sc.drivers["r_v2"].cmd_delay_s = 1.0
    run = sc.pause()
    assert run.error is None, f"pause бросил {run.error!r}"
    assert run.elapsed <= 1.5, f"pause вернулся за {run.elapsed:.2f} с"
    belt_stops = sc.drivers["belt"].stops()
    assert len(belt_stops) == 1, f"стопов ленты: {len(belt_stops)}"
    assert belt_stops[0][2] - run.t0 <= 0.3, f"стоп ленты через {belt_stops[0][2] - run.t0:.2f} с после старта pause"


def _failing_belt_scene(make_scene: Callable[..., Scene], *, clock: bool = False) -> Scene:
    sc = make_scene(_THREE, clock=clock)
    sc.drivers["belt"].reply = {"status": "error"}
    return sc


def test_r9b_failed_pause_thrice_raises_and_repeats_only_failed_device(make_scene: Callable[..., Scene]) -> None:
    sc = _failing_belt_scene(make_scene)
    errors = [sc.pause().error for _ in range(3)]
    assert all(isinstance(e, RuntimeError) for e in errors), f"исключения трёх pause: {errors}"
    assert [(a[0], a[1]) for a in sc.drivers["r_v2"].stops()] == [("stop", {"level": "SOFT"})]
    assert [(a[0], a[1]) for a in sc.drivers["r_v1"].stops()] == [("abort", {"mode": 3})]
    assert [(a[0], a[1]) for a in sc.drivers["belt"].stops()] == [("stop", {})] * 3


def test_r9b_resume_forgets_stops_and_robot_is_stopped_again(make_scene: Callable[..., Scene]) -> None:
    sc = _failing_belt_scene(make_scene)
    for _ in range(3):
        assert isinstance(sc.pause().error, RuntimeError)
    assert len(sc.drivers["r_v2"].stops()) == 1
    sc.resume()
    assert isinstance(sc.pause().error, RuntimeError)
    assert len(sc.drivers["r_v2"].stops()) == 2


def test_r9c_pause_after_clock_jump_stops_robot_again(make_scene: Callable[..., Scene]) -> None:
    sc = _failing_belt_scene(make_scene, clock=True)
    assert isinstance(sc.pause().error, RuntimeError)
    assert len(sc.drivers["r_v2"].stops()) == 1
    sc.drivers["belt"].reply = {"status": "ok"}
    assert sc.clock is not None
    sc.clock.jump(10.0)
    run = sc.pause()
    assert run.error is None, f"второй pause бросил {run.error!r}"
    assert len(sc.drivers["r_v2"].stops()) == 2


def test_r9d_second_pause_without_resume_stops_again(make_scene: Callable[..., Scene]) -> None:
    sc = make_scene(_THREE)
    assert sc.pause().error is None
    assert len(sc.drivers["r_v2"].stops()) == 1
    assert sc.pause().error is None
    assert len(sc.drivers["r_v2"].stops()) == 2


# ==================================================================================================
# 10. Единственный писатель и бюджет паузы
# ==================================================================================================


def test_r10a_tick_worker_record_then_failed_connect_gives_error(make_scene: Callable[..., Scene]) -> None:
    sc = make_scene(params=_STEPWISE)
    sc.start_worker()

    def tick_record_seen() -> bool:
        rec = sc.last_conn_record()
        return isinstance(rec, dict) and rec.get("conn") == "connected" and type(rec.get("ts")) is int

    until(tick_record_seen, 3.0, "запись воркера {conn: connected, ts: int}")
    rec = sc.last_conn_record()
    assert set(rec) == {"conn", "ts"} and rec["conn"] == "connected" and type(rec["ts"]) is int, rec
    drv = sc.drivers[_DEV]
    drv.connect_ok = False
    drv.up = False
    bounded(lambda: sc.plugin._manager.connect(_DEV))
    until(lambda: sc.last_conn_record() == {"conn": "error"}, 3.0, "последняя запись {conn: error}")
    sc.wait_readiness(_LINK_ERROR, 1.5)


def test_r10b_foreign_publish_does_not_change_connection_fact(make_scene: Callable[..., Scene]) -> None:
    sc = make_scene()
    assert sc.readiness() == [], "обвязка: после подключения очередью устройство должно быть готово"
    sc.plugin._publish_state("devices.state.robot_main.conn", {"conn": "error"})
    sc.plugin._publish_state("devices.state.robot_main.last_error", "boom")
    sc.plugin._publish_state("devices.state.robot_main.status", {"conn": "error"})
    sc.plugin._publish_state("devices.state.robot_main.conn", {"ts": 5})
    sc.plugin._publish_state("devices.state.robot_main", {})
    assert sc.readiness() == []


def test_r10c_budget_constants() -> None:
    from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import _SHUTDOWN_LOCK_SEC
    from Plugins.hub.device_hub.plugin import _PAUSE_BUDGET_S

    assert _PAUSE_BUDGET_S == 1.5
    assert _SHUTDOWN_LOCK_SEC == 2.0
    assert _PAUSE_BUDGET_S < _SHUTDOWN_LOCK_SEC


def test_r10c_slow_command_raises_within_budget(make_scene: Callable[..., Scene]) -> None:
    sc = make_scene(_THREE)
    sc.drivers["r_v2"].cmd_delay_s = 3.0
    run = sc.pause()
    assert isinstance(run.error, RuntimeError), f"pause вместо RuntimeError дал {run.error!r}"
    assert run.elapsed <= 1.8, f"pause вернулся за {run.elapsed:.2f} с"


def test_r10c_slow_command_gives_exactly_one_scope_incident(make_scene: Callable[..., Scene]) -> None:
    sc = make_scene(_THREE)
    sc.drivers["r_v2"].cmd_delay_s = 3.0
    assert sc.scope_incidents() == []
    sc.pause()
    until(lambda: len(sc.scope_incidents()) >= 1, 1.0, "инцидент device_hub.scope")
    time.sleep(0.3)
    assert len(sc.scope_incidents()) == 1, f"инцидентов: {sc.scope_incidents()}"


def test_r10c_pause_does_not_mark_plugin_shutting_down(make_scene: Callable[..., Scene]) -> None:
    sc = make_scene(_THREE)
    sc.drivers["r_v2"].cmd_delay_s = 3.0
    sc.pause()
    assert sc.plugin._shutting_down is False


def test_r10c_disconnected_device_is_skipped(make_scene: Callable[..., Scene]) -> None:
    sc = make_scene(_THREE)
    assert sc.plugin.cmd_device_disconnect({"device_id": "belt"})["status"] == "ok"
    bounded(sc.plugin._process_conn_queue)
    assert sc.drivers["belt"].is_connected is False
    run = sc.pause()
    assert run.error is None, f"pause бросил {run.error!r}"
    assert _stop_counts(sc) == {"r_v2": 1, "r_v1": 1, "belt": 0}


def test_r10c_resume_sends_no_command(make_scene: Callable[..., Scene]) -> None:
    sc = make_scene(_THREE)
    assert sc.pause().error is None
    before = {dev_id: drv.commands() for dev_id, drv in sc.drivers.items()}
    assert before == {"r_v2": 1, "r_v1": 1, "belt": 1}
    sc.resume()
    time.sleep(0.3)
    assert {dev_id: drv.commands() for dev_id, drv in sc.drivers.items()} == before
