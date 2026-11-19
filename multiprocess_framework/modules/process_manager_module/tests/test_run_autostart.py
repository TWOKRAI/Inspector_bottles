# -*- coding: utf-8 -*-
"""Срез S3c (system-run-state 2.7) — слепые приёмочные тесты автостарта работы один раз за boot.

Написано ДО реализации по наблюдаемому контракту брифа (DESIGN, ``plans/**`` и тела ``process/**`` не читались).

Контракт: PM с ключами ``run_gate: true`` и ``run_autostart: true`` при первом входе машины ``system.run.state``
в ``ready`` (из ``booting`` или ``not_ready``) сам подаёт START как команду ``system.run.start``; за жизнь PM — не
больше одного раза. Автостарт отменяют ранее пришедшие ``system.run.stop`` / ``system.run.ack`` / ``topology.apply``
(принятые или отказанные); отказанный START оператора (``not_ready``) его не отменяет. Ключи читаются один раз при
создании компонентов PM (ставятся ``pm.update_config`` ДО ``pm._create_components()``).

Наблюдаемое: счёт записей значения ``"running"`` по пути ``system.run.state`` в журнале двойника стора, событие
работы ``pm._run_event`` и тексты WARNING (``pm._log_warning``). Ожидаемые значения — литералы.

Помощники: H1 ``_autostart_pm`` (копия ``make_readiness_pm`` без финального ``settled`` и с ключом автостарта),
H2 ``_AutostartRig`` (копия ``_Rig`` из ``test_run_stop`` без шагов ``pre_stop``, тот же ключ, стор до boot).
Подача событий идёт в daemon-потоке с ``join(3)``: зависание — красный, не висящий прогон.
"""

from __future__ import annotations

import copy
import threading
import time
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest

from ..core.stop_budget import stop_budget
from ..monitor.process_monitor import ProcessMonitor
from ..process.process_manager_process import ProcessManagerProcess
from .conftest import make_monitor_double, make_pm, wire_planner
from .test_run_commands import _PM_MOD, beat, tick
from .test_run_stop import (
    _TIMEOUT_S,
    _ChildSim,
    _LoggedEvent,
    _StepRouter,
    _StopEventSpy,
)

_CAM = {"cam": {"class": "pkg.Cam"}}
_ABSENT = object()  # «ключа run_autostart нет»
_JOIN_S = 3.0  # join-дедлайн подачи события / ожидание START
_QUIET_S = 2.0  # «нет START» = столько тишины
_STATE_PATH = "system.run.state"

_W_AUTOSTART_LOG = "автостарт: system.run.start (run_autostart)"
_W_BAD_VALUE = "run_autostart негоден (нужно true или false) — автостарт выключен"
_W_NO_GATE = "run_autostart без run_gate — автостарт не действует"


# --------------------------------------------------------------------------- #
# Общие вспомогательные
# --------------------------------------------------------------------------- #


class _Store:
    """Двойник стора: журнал записей ``(path, value)`` (образец ``_Store`` из ``test_run_commands``)."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, Any]] = []
        self._lock = threading.Lock()

    def handle_state_set(self, msg: dict) -> dict:
        data = msg["data"]
        with self._lock:
            self.writes.append((data["path"], data["value"]))
        return {"status": "ok", "path": data["path"], "changed": True}

    def snapshot(self) -> list[tuple[str, Any]]:
        with self._lock:
            return list(self.writes)


def _bounded(fn: Callable[[], Any], deadline_s: float = _JOIN_S) -> Any:
    """Вызвать ``fn`` в daemon-потоке с join-дедлайном: зависший вызов — упавший ассерт, не зависший прогон."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробросим в поток теста
            box["error"] = exc

    th = threading.Thread(target=run, daemon=True, name="autostart-bounded")
    th.start()
    th.join(deadline_s)
    assert not th.is_alive(), f"вызов завис дольше {deadline_s} с"
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _wait(predicate: Callable[[], bool], timeout: float) -> bool:
    """Ждать условие до дедлайна; итог — выполнилось ли."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


def _starts(store: _Store) -> int:
    """Сколько раз значение ``"running"`` записано по пути ``system.run.state``."""
    return sum(1 for path, value in store.snapshot() if path == _STATE_PATH and value == "running")


def _wait_starts(store: _Store, n: int, timeout: float = _JOIN_S) -> bool:
    return _wait(lambda: _starts(store) >= n, timeout)


def _assert_starts_stay(store: _Store, n: int, quiet_s: float = _QUIET_S) -> None:
    """``quiet_s`` секунд тишины: счёт START всё время равен ``n`` (ни один лишний не проскакивает)."""
    end = time.monotonic() + quiet_s
    while time.monotonic() < end:
        assert _starts(store) == n, store.snapshot()
        time.sleep(0.01)
    assert _starts(store) == n, store.snapshot()


def _warnings(pm: ProcessManagerProcess) -> list[str]:
    """Тексты WARNING PM (все позиционные аргументы вызова склеены пробелом)."""
    return [" ".join(str(a) for a in c.args) for c in pm._log_warning.call_args_list if c.args]


def _state(pm: ProcessManagerProcess) -> str:
    return pm._run_snapshot()[0].value


def _settle(pm: ProcessManagerProcess, ready: bool) -> None:
    """Итог boot-барьера: шов, которым ``initialize()`` сообщает машине ``settled``."""
    _bounded(lambda: pm._run_apply("settled", ready=ready))


def _tick(pm: ProcessManagerProcess, monitor: ProcessMonitor) -> None:
    _bounded(lambda: tick(pm, monitor))


def _beat(monitor: ProcessMonitor, name: str = "cam") -> None:
    _bounded(lambda: beat(monitor, name))


# --------------------------------------------------------------------------- #
# H1 — PM + настоящий монитор, boot подаёт тест
# --------------------------------------------------------------------------- #


def _autostart_pm(
    configs: dict[str, dict], *, run_gate: bool, run_autostart: Any
) -> tuple[ProcessManagerProcess, ProcessMonitor, _Store]:
    """Копия ``make_readiness_pm`` с двумя отличиями: ключ ``run_autostart`` ставится до ``_create_components()``
    (``_ABSENT`` — не писать вовсе); финального ``settled`` нет (состояние после сборки — ``booting``).
    Стор — свой двойник, подключён сразу."""
    pm = make_pm(process_configs=configs)
    registry = pm._process_registry  # MockProcessRegistry с живыми MockProcess по ключам configs
    pm.update_config("run_gate", run_gate)
    if run_autostart is not _ABSENT:
        pm.update_config("run_autostart", run_autostart)
    pm.update_config("heartbeat_interval", 5.0)
    pm.update_config("heartbeat_interval_sec", 5.0)
    with (
        patch(f"{_PM_MOD}.ProcessRegistry"),
        patch(f"{_PM_MOD}.ProcessPriority"),
        patch(f"{_PM_MOD}.ProcessStatusMonitor"),
        patch(f"{_PM_MOD}.ProcessMonitor", return_value=make_monitor_double()),
        patch(f"{_PM_MOD}.QueueRegistry"),
    ):
        pm._create_components()
    pm._process_registry = registry
    monitor = ProcessMonitor(pm, poll_interval=0.01, heartbeat_timeout=15.0)
    pm._process_monitor = monitor
    pm.communication = MagicMock()
    pm.communication.broadcast.return_value = 1  # число получателей: монитор сравнивает его с нулём
    pm.router_manager = MagicMock()
    store = _Store()
    pm._state_store_manager = store
    return pm, monitor, store


# --------------------------------------------------------------------------- #
# H2 — копия _Rig: PM + монитор + двойник детей (живой цикл heartbeat), стор до boot
# --------------------------------------------------------------------------- #


class _AutostartRig:
    """Копия ``_Rig`` из ``test_run_stop`` (без шагов ``pre_stop``): ``run_autostart`` ставится до
    ``_create_components()``, финального ``settled`` в конструкторе нет, стор стоит до boot; boot — ``boot()``."""

    def __init__(self, names: tuple[str, ...] = ("cam",), *, timeout_s: float = _TIMEOUT_S) -> None:
        configs = {n: {"class": f"pkg.{n}"} for n in names}
        pm = make_pm(process_configs=configs)
        registry = pm._process_registry
        pm.update_config("run_gate", True)
        pm.update_config("run_autostart", True)
        pm.update_config("heartbeat_interval", 5.0)
        pm.update_config("heartbeat_interval_sec", 5.0)
        pm.update_config("run_stop_timeout_s", timeout_s)
        with (
            patch(f"{_PM_MOD}.ProcessRegistry"),
            patch(f"{_PM_MOD}.ProcessPriority"),
            patch(f"{_PM_MOD}.ProcessStatusMonitor"),
            patch(f"{_PM_MOD}.ProcessMonitor"),
            patch(f"{_PM_MOD}.QueueRegistry"),
        ):
            pm._create_components()
        pm._process_registry = registry
        monitor = ProcessMonitor(pm, poll_interval=0.01, heartbeat_timeout=15.0)
        pm._process_monitor = monitor
        pm.communication = MagicMock()
        pm.communication.broadcast.return_value = 1
        pm.attach_stop_budget(stop_budget(5.0))
        self.log: list[str] = []
        self.state_at_stop_events: list[str] = []
        pm._run_event = _LoggedEvent(pm._run_event, self.log)
        pm._system_stop_event = _StopEventSpy(self)
        self.router = _StepRouter(self, False)
        pm.router_manager = self.router
        self.store = _Store()
        pm._state_store_manager = self.store
        self.pm = pm
        self.monitor = monitor
        self.sim = _ChildSim(pm, monitor, names)

    def close(self) -> None:
        self.sim.close()
        self.router.gate.set()

    def boot(self) -> None:
        """Дети отчитались -> итог boot-барьера ``settled(ready=True)`` (в daemon-потоке с дедлайном)."""
        _bounded(self.sim.beat_now)
        _settle(self.pm, True)

    def tick(self) -> None:
        _tick(self.pm, self.monitor)

    def stop(self) -> dict:
        """``system.run.stop`` в daemon-потоке с дедлайном."""
        return _bounded(self.pm._cmd_system_run_stop)

    @property
    def state(self) -> str:
        return _state(self.pm)

    def wait_not_stopping(self, timeout: float = _JOIN_S) -> bool:
        return _wait(lambda: self.state != "stopping", timeout)

    def status(self) -> dict:
        return self.pm._cmd_system_run_status()


@pytest.fixture
def rig():
    r = _AutostartRig()
    try:
        yield r
    finally:
        r.close()


# --------------------------------------------------------------------------- #
# 1-2, 7. Автостарт срабатывает
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_autostart_fires_once_on_first_ready() -> None:
    """1. ``beat`` -> ``settled(ready=True)`` -> ровно один ``running`` за 3 с; событие работы взведено; ровно одна
    WARNING «автостарт: system.run.start (run_autostart)»."""
    pm, monitor, store = _autostart_pm(_CAM, run_gate=True, run_autostart=True)
    _beat(monitor)

    _settle(pm, True)

    assert _wait_starts(store, 1), store.snapshot()
    assert _wait(pm._run_event.is_set, _JOIN_S), "событие работы не взведено после автостарта"
    assert pm._run_event.is_set() is True
    _assert_starts_stay(store, 1, 0.5)
    assert _warnings(pm).count(_W_AUTOSTART_LOG) == 1, _warnings(pm)


@pytest.mark.timeout(60)
def test_autostart_fires_on_entry_to_ready_from_not_ready() -> None:
    """2. ``settled(ready=False)`` -> ``not_ready`` (автостарта нет); ``beat`` + такт -> вход в ``ready`` -> один
    ``running``."""
    pm, monitor, store = _autostart_pm(_CAM, run_gate=True, run_autostart=True)

    _settle(pm, False)
    assert _state(pm) == "not_ready"
    assert _starts(store) == 0, store.snapshot()

    _beat(monitor)
    _tick(pm, monitor)

    assert _wait_starts(store, 1), store.snapshot()
    _assert_starts_stay(store, 1, 0.5)


@pytest.mark.timeout(60)
def test_refused_operator_start_does_not_cancel_autostart() -> None:
    """7. ``not_ready`` -> START оператора отказан (``success`` False, ``error`` ``not_ready``) -> ``beat`` + такт ->
    автостарт всё же один раз."""
    pm, monitor, store = _autostart_pm(_CAM, run_gate=True, run_autostart=True)
    _settle(pm, False)

    reply = _bounded(pm._cmd_system_run_start)

    assert reply["success"] is False, reply
    assert reply["error"] == "not_ready", reply
    assert _starts(store) == 0, store.snapshot()

    _beat(monitor)
    _tick(pm, monitor)

    assert _wait_starts(store, 1), store.snapshot()
    _assert_starts_stay(store, 1, 0.5)


# --------------------------------------------------------------------------- #
# 3, 4, 9. После автостарта второго START нет
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_no_second_start_after_stop(rig: _AutostartRig) -> None:
    """3. ``boot`` -> START (счёт 1) -> ``stop`` -> ``ready`` -> 2 с: счёт остаётся 1."""
    rig.boot()
    assert _wait_starts(rig.store, 1), rig.store.snapshot()

    rig.stop()
    assert rig.wait_not_stopping(), rig.status()
    assert rig.state == "ready", rig.status()

    _assert_starts_stay(rig.store, 1)


@pytest.mark.timeout(60)
def test_no_second_start_after_fault_and_ack(rig: _AutostartRig) -> None:
    """4. ``boot`` -> START -> потеря готовности + такт -> ``fault``; готовность вернулась, ``ack`` принят
    (опрос <= 3 с) -> ``ready`` -> 2 с: счёт остаётся 1."""
    rig.boot()
    assert _wait_starts(rig.store, 1), rig.store.snapshot()

    rig.sim.set("cam", ready=False)
    _bounded(rig.sim.beat_now)  # свежий отчёт ``ready: false`` в мониторе до такта (без гонки с потоком детей)
    rig.tick()
    assert rig.state == "fault", rig.status()

    rig.sim.set("cam", ready=True)
    _bounded(rig.sim.beat_now)
    acked: list[dict] = []

    def ack_ok() -> bool:
        reply = _bounded(rig.pm._cmd_system_run_ack)
        acked.append(reply)
        return reply.get("success") is True

    assert _wait(ack_ok, _JOIN_S), acked[-3:]
    assert rig.state == "ready", rig.status()

    _assert_starts_stay(rig.store, 1)


@pytest.mark.timeout(60)
def test_no_second_start_after_readiness_lost_and_back(rig: _AutostartRig) -> None:
    """9. ``boot`` -> START -> ``stop`` -> ``ready``; процесс перезапущен: потеря готовности + такт -> ``not_ready``,
    возврат + такт -> ``ready`` -> 2 с: счёт остаётся 1."""
    rig.boot()
    assert _wait_starts(rig.store, 1), rig.store.snapshot()
    rig.stop()
    assert rig.wait_not_stopping(), rig.status()
    assert rig.state == "ready", rig.status()

    rig.sim.set("cam", ready=False)
    _bounded(rig.sim.beat_now)
    rig.tick()
    assert rig.state == "not_ready", rig.status()

    rig.sim.set("cam", ready=True)
    _bounded(rig.sim.beat_now)
    rig.tick()
    assert rig.state == "ready", rig.status()

    _assert_starts_stay(rig.store, 1)


# --------------------------------------------------------------------------- #
# 5, 6, 10. Раньше пришедшая команда отменяет автостарт
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_topology_apply_cancels_autostart() -> None:
    """5. ``not_ready`` -> ``topology.apply`` (успех) -> ``booting`` -> довести до ``ready`` -> 2 с: счёт 0."""
    pm, monitor, store = _autostart_pm(_CAM, run_gate=True, run_autostart=True)
    # ``_create_components`` обнуляет менеджер топологии (его строит ``initialize``): поднимаем, как в
    # ``test_run_apply_gate``
    pm._setup_topology_manager()
    wire_planner(pm)
    pm._ensure_routing_state()
    _settle(pm, False)
    assert _state(pm) == "not_ready"

    topology = {"processes": [{"process_name": "cam", "process_class": "pkg.Cam"}]}
    reply = _bounded(lambda: pm._cmd_topology_apply({"topology_dict": copy.deepcopy(topology)}))

    assert reply.get("success") is True, reply
    # ``apply`` прошёл через ``booting``: значение опубликовано в журнале стора (после ответа машина уже могла осесть)
    published = [v for p, v in store.snapshot() if p == _STATE_PATH]
    assert "booting" in published, published

    _beat(monitor)
    _tick(pm, monitor)
    if not _wait(lambda: _state(pm) == "ready", _JOIN_S):
        _settle(pm, True)  # PM сам итог boot-барьера после apply не подал
    assert _wait(lambda: _state(pm) == "ready", _JOIN_S), pm._run_snapshot()

    _assert_starts_stay(store, 0)


@pytest.mark.timeout(60)
def test_stop_cancels_autostart() -> None:
    """6. ``not_ready`` -> ``system.run.stop`` (принят или отказан) -> ``beat`` + такт -> ``ready`` -> 2 с: счёт 0."""
    pm, monitor, store = _autostart_pm(_CAM, run_gate=True, run_autostart=True)
    _settle(pm, False)
    assert _state(pm) == "not_ready"

    _bounded(pm._cmd_system_run_stop)
    _beat(monitor)
    _tick(pm, monitor)

    assert _state(pm) == "ready", pm._run_snapshot()
    _assert_starts_stay(store, 0)


@pytest.mark.timeout(60)
def test_ack_cancels_autostart() -> None:
    """10. ``not_ready`` -> ``system.run.ack`` отказан (``error`` ``no_fault``) -> ``beat`` + такт -> ``ready`` ->
    2 с: счёт 0."""
    pm, monitor, store = _autostart_pm(_CAM, run_gate=True, run_autostart=True)
    _settle(pm, False)
    assert _state(pm) == "not_ready"

    reply = _bounded(pm._cmd_system_run_ack)

    assert reply["success"] is False, reply
    assert reply["error"] == "no_fault", reply

    _beat(monitor)
    _tick(pm, monitor)

    assert _state(pm) == "ready", pm._run_snapshot()
    _assert_starts_stay(store, 0)


# --------------------------------------------------------------------------- #
# 8. Автостарта нет: ключ выключен / отсутствует / негоден / без run_gate
# --------------------------------------------------------------------------- #


def _boot_ready(pm: ProcessManagerProcess, monitor: ProcessMonitor) -> None:
    _beat(monitor)
    _settle(pm, True)


@pytest.mark.timeout(60)
@pytest.mark.parametrize("run_autostart", [False, _ABSENT], ids=["key-false", "key-absent"])
def test_autostart_off_is_silent(run_autostart: Any) -> None:
    """8 (a, b). ``run_autostart`` ``false`` / ключа нет: счёт 0 и ни одной WARNING со словом «run_autostart»."""
    pm, monitor, store = _autostart_pm(_CAM, run_gate=True, run_autostart=run_autostart)

    _boot_ready(pm, monitor)

    assert _state(pm) == "ready", pm._run_snapshot()
    _assert_starts_stay(store, 0)
    assert [w for w in _warnings(pm) if "run_autostart" in w] == [], _warnings(pm)


@pytest.mark.timeout(60)
def test_autostart_bad_value_warns_once_without_value() -> None:
    """8 (c). ``run_autostart`` = ``"yes"``: автостарта нет; ровно одна WARNING с «run_autostart» (дословный текст),
    ни одна WARNING не содержит значения ``yes``."""
    pm, monitor, store = _autostart_pm(_CAM, run_gate=True, run_autostart="yes")

    _boot_ready(pm, monitor)

    assert _state(pm) == "ready", pm._run_snapshot()
    _assert_starts_stay(store, 0)
    about_key = [w for w in _warnings(pm) if "run_autostart" in w]
    assert about_key == [_W_BAD_VALUE], _warnings(pm)
    assert [w for w in _warnings(pm) if "yes" in w] == [], _warnings(pm)


@pytest.mark.timeout(60)
def test_autostart_without_run_gate_warns_once() -> None:
    """8 (d). ``run_autostart`` = ``true`` при ``run_gate`` = ``false``: автостарта нет; ровно одна WARNING
    «run_autostart без run_gate — автостарт не действует»."""
    pm, monitor, store = _autostart_pm(_CAM, run_gate=False, run_autostart=True)

    _boot_ready(pm, monitor)

    _assert_starts_stay(store, 0)
    about_key = [w for w in _warnings(pm) if "run_autostart" in w]
    assert about_key == [_W_NO_GATE], _warnings(pm)
