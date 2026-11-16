# -*- coding: utf-8 -*-
"""Срез S3c (system-run-state 2.7, ADR-PMM-050) — авторские тесты автостарта: таблица латча, подача через
исполнитель жизненного цикла, отказанный автостарт, настоящий ``pm-lifecycle``, гонки.

S3c 11 — ``AutostartLatch`` как чистая функция, литералы таблицы.
S3c 12 — исполнитель не взял подачу (отказ ``executor_busy``, ``False`` без ответа, исключение) -> START на
одноразовом daemon-потоке, ``running`` ровно 1 раз.
S3c 13 — автостарт отказан (готовность ушла между тактом и START) -> одна WARNING «автостарт отказан: not_ready»,
повтора нет; оператор успел START (``already_running``) -> одна INFO, WARNING об отказе нет.
S3c 14 — настоящий ``pm-lifecycle`` (``WorkerManager`` + ``ExecutorManager``): START взял исполнитель, не обход.
Гонки — 20 потоков такта в ``ready`` и START оператора наперегонки с автостартом: ``running`` ровно 1 раз.

Каждая подача события (``_run_apply``, команда, такт) идёт в daemon-потоке с ``join``-дедлайном: синхронный
START под ``_run_lock`` (замок не реентерабелен) — красный, а не зависший прогон.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest

from ...worker_module import WorkerManager
from ...worker_module.executor_manager import ExecutorManager
from ..monitor.process_monitor import ProcessMonitor
from ..process.process_manager_process import ProcessManagerProcess
from ..process.run_state import RunState
from .conftest import make_monitor_double, make_pm
from .test_run_commands import _PM_MOD, beat, tick

_CAM = {"cam": {"class": "pkg.Cam"}}
_JOIN_S = 3.0
_QUIET_S = 2.0
_STATE_PATH = "system.run.state"

_W_AUTOSTART = "автостарт: system.run.start (run_autostart)"
_W_REFUSED_NOT_READY = "автостарт отказан: not_ready"
_W_REFUSED_PREFIX = "автостарт отказан"
_I_ALREADY_RUNNING = "автостарт не нужен: линия уже в работе (already_running)"
_W_EXECUTOR_BUSY = "run-autostart: исполнитель отказал (executor_busy) — последовательность на своём потоке"
_W_EXECUTOR_FALSE = "run-autostart: исполнитель вернул False без ответа — последовательность на своём потоке"
_E_EXECUTOR_RAISED = "run-autostart: исполнитель не принял последовательность (RuntimeError)"


# --------------------------------------------------------------------------- #
# Помощники (свои: ``conftest.py`` вне FILES, ``make_run_pm`` сразу подаёт ``settled``)
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

    def starts(self) -> int:
        with self._lock:
            return sum(1 for p, v in self.writes if p == _STATE_PATH and v == "running")


def _bounded(fn: Callable[[], Any], deadline_s: float = _JOIN_S) -> Any:
    """``fn`` в daemon-потоке с join-дедлайном: зависание — упавший ассерт, не зависший прогон."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробросим в поток теста
            box["error"] = exc

    th = threading.Thread(target=run, daemon=True, name="autostart-hazard-bounded")
    th.start()
    th.join(deadline_s)
    assert not th.is_alive(), f"вызов завис дольше {deadline_s} с"
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _wait(predicate: Callable[[], bool], timeout: float = _JOIN_S) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


def _stay(store: _Store, n: int, quiet_s: float = _QUIET_S) -> None:
    """``quiet_s`` секунд счёт START всё время равен ``n``."""
    end = time.monotonic() + quiet_s
    while time.monotonic() < end:
        assert store.starts() == n, store.writes
        time.sleep(0.01)
    assert store.starts() == n, store.writes


def _texts(mock: MagicMock) -> list[str]:
    return [" ".join(str(a) for a in c.args) for c in mock.call_args_list if c.args]


def _state(pm: ProcessManagerProcess) -> str:
    return pm._run_snapshot()[0].value


def _pm(*, run_autostart: Any = True, run_gate: bool = True) -> tuple[ProcessManagerProcess, ProcessMonitor, _Store]:
    """PM + настоящий монитор; ``run_gate``/``run_autostart`` ДО ``_create_components()``; boot подаёт тест."""
    pm = make_pm(process_configs=dict(_CAM))
    registry = pm._process_registry
    pm.update_config("run_gate", run_gate)
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
    pm.communication.broadcast.return_value = 1
    pm.router_manager = MagicMock()
    store = _Store()
    pm._state_store_manager = store
    return pm, monitor, store


class _HeldSubmit:
    """Двойник ``_lifecycle_submit``: берёт подачу и держит её; тест сам выполняет ``action`` в нужный момент."""

    def __init__(self) -> None:
        self.actions: list[Callable[[], Any]] = []
        self.replies: list[Callable[[Any], None]] = []
        self.taken = threading.Event()

    def submit(self, action: Callable[[], Any], _data: Any, on_reply: Callable[[Any], None]) -> bool:
        self.actions.append(action)
        self.replies.append(on_reply)
        self.taken.set()
        return True

    def run_held(self) -> Any:
        result = self.actions[0]()
        self.replies[0](result)
        return result


# --------------------------------------------------------------------------- #
# S3c 11 — таблица латча (чистая функция)
# --------------------------------------------------------------------------- #

_B, _NR, _R, _RUN, _STP, _F = (
    RunState.booting,
    RunState.not_ready,
    RunState.ready,
    RunState.running,
    RunState.stopping,
    RunState.fault,
)

# Последовательности ``(event, prev, new, code, ожидаемый итог observe)`` для ВЗВЕДЁННОГО латча.
_ARMED_SEQUENCES: dict[str, list[tuple[str, RunState, RunState, str | None, bool]]] = {
    "settled-booting-fires-once": [("settled", _B, _R, None, True), ("settled", _B, _R, None, False)],
    "tick-not-ready-fires": [("tick", _NR, _R, None, True), ("tick", _NR, _R, None, False)],
    "tick-from-stopping-ignored": [("tick", _STP, _R, None, False), ("tick", _NR, _R, None, True)],
    "settled-from-fault-ignored": [("settled", _F, _R, None, False), ("tick", _NR, _R, None, True)],
    "settled-from-stopping-ignored": [("settled", _STP, _R, None, False), ("tick", _NR, _R, None, True)],
    "refused-start-keeps-latch": [("start", _R, _NR, "not_ready", False), ("tick", _NR, _R, None, True)],
    "accepted-start-cancels": [("start", _R, _RUN, None, False), ("tick", _NR, _R, None, False)],
    "refused-tick-code-ignored": [("tick", _NR, _R, "x", False), ("tick", _NR, _R, None, True)],
    "tick-stays-not-ready": [("tick", _NR, _NR, None, False), ("tick", _NR, _R, None, True)],
    "settled-to-not-ready": [("settled", _B, _NR, None, False), ("tick", _NR, _R, None, True)],
    "unknown-event-ignored": [("noise", _NR, _R, None, False), ("tick", _NR, _R, None, True)],
}
for _event in ("stop", "apply", "ack", "shutdown"):
    for _code in (None, "x"):
        _ARMED_SEQUENCES[f"{_event}-code-{_code}-cancels"] = [
            (_event, _NR, _NR, _code, False),
            ("settled", _B, _R, None, False),
        ]


def _latch(enabled: bool) -> Any:
    from ..process.run_state import AutostartLatch  # импорт тут: до кода красны тесты, не сбор файла

    return AutostartLatch(enabled)


def test_latch_disabled_never_fires() -> None:
    """11. Выключенный латч: вход в ``ready`` из ``booting``/``not_ready`` -> ``False``."""
    latch = _latch(False)
    assert latch.observe("settled", _B, _R, None) is False
    assert latch.observe("tick", _NR, _R, None) is False


@pytest.mark.parametrize("steps", list(_ARMED_SEQUENCES.values()), ids=list(_ARMED_SEQUENCES))
def test_latch_table(steps: list[tuple[str, RunState, RunState, str | None, bool]]) -> None:
    """11. Взведённый латч: каждая строка последовательности даёт ожидаемый литерал."""
    latch = _latch(True)
    got = [latch.observe(event, prev, new, code) for event, prev, new, code, _want in steps]
    assert got == [want for *_rest, want in steps], steps


# --------------------------------------------------------------------------- #
# S3c 12 — исполнитель не взял подачу: START на одноразовом daemon-потоке
# --------------------------------------------------------------------------- #


class _BusySubmit:
    """Отказ по контракту ``OrderedExecutor.submit``: ``reply`` с ``executor_busy`` сразу."""

    def submit(self, _action: Any, _data: Any, on_reply: Callable[[Any], None]) -> bool:
        on_reply({"success": False, "error": "executor_busy"})
        return False


class _FalseSubmit:
    """Возврат ``False`` без ``reply``."""

    def submit(self, _action: Any, _data: Any, _on_reply: Any) -> bool:
        return False


class _RaisingSubmit:
    """Исключение подачи."""

    def submit(self, _action: Any, _data: Any, _on_reply: Any) -> bool:
        raise RuntimeError("submit failed")


@pytest.mark.timeout(60)
@pytest.mark.parametrize(
    ("submit", "log_attr", "text"),
    [
        (_BusySubmit(), "_log_warning", _W_EXECUTOR_BUSY),
        (_FalseSubmit(), "_log_warning", _W_EXECUTOR_FALSE),
        (_RaisingSubmit(), "_log_error", _E_EXECUTOR_RAISED),
    ],
    ids=["executor-busy", "false-no-reply", "submit-raises"],
)
def test_executor_refusal_runs_autostart_on_own_thread(submit: Any, log_attr: str, text: str) -> None:
    """12. Исполнитель не взял автостарт -> START на потоке ``run-autostart``; ``running`` ровно 1 раз."""
    pm, monitor, store = _pm()
    pm._lifecycle_submit = submit
    threads: list[str] = []
    original_start = pm._cmd_system_run_start

    def recording_start(*args: Any, **kwargs: Any) -> dict:
        threads.append(threading.current_thread().name)
        return original_start(*args, **kwargs)

    pm._cmd_system_run_start = recording_start
    _bounded(lambda: beat(monitor, "cam"))

    _bounded(lambda: pm._run_apply("settled", ready=True))

    assert _wait(lambda: store.starts() >= 1), store.writes
    _stay(store, 1, 0.5)
    assert threads == ["run-autostart"], threads
    assert _texts(getattr(pm, log_attr)).count(text) == 1, _texts(getattr(pm, log_attr))
    assert pm._run_event.is_set() is True


# --------------------------------------------------------------------------- #
# S3c 13 — автостарт отказан / оператор успел: без повтора
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_refused_autostart_warns_code_and_does_not_retry() -> None:
    """13a. Готовность ушла между тактом и START -> одна WARNING «автостарт отказан: not_ready» (без причин);
    готовность вернулась (такт -> ``ready``) -> 2 с без ``running``."""
    pm, monitor, store = _pm()
    held = _HeldSubmit()
    pm._lifecycle_submit = held
    _bounded(lambda: beat(monitor, "cam"))
    _bounded(lambda: pm._run_apply("settled", ready=True))
    assert held.taken.wait(_JOIN_S), "автостарт не подан исполнителю"
    assert _state(pm) == "ready"

    lost = [{"node": "cam", "reason": "camera_lost", "source": "plugin", "severity": "failure"}]
    with patch.object(pm, "_evaluate_or_fail", return_value=(False, lost)):
        _bounded(held.run_held)

    warnings = _texts(pm._log_warning)
    assert [w for w in warnings if w.startswith(_W_REFUSED_PREFIX)] == [_W_REFUSED_NOT_READY], warnings
    assert [w for w in warnings if "camera_lost" in w] == [], warnings
    assert _state(pm) == "not_ready"

    _bounded(lambda: beat(monitor, "cam"))
    _bounded(lambda: tick(pm, monitor))
    assert _state(pm) == "ready", pm._run_snapshot()
    _stay(store, 0)
    assert len(held.actions) == 1, "автостарт подан повторно"
    assert _texts(pm._log_warning).count(_W_AUTOSTART) == 1


@pytest.mark.timeout(60)
def test_operator_start_first_gives_info_not_warning() -> None:
    """13b. Оператор успел START до автостарта -> ``already_running``: одна INFO, ни одной WARNING «автостарт
    отказан»; ``running`` ровно 1 раз."""
    pm, monitor, store = _pm()
    held = _HeldSubmit()
    pm._lifecycle_submit = held
    _bounded(lambda: beat(monitor, "cam"))
    _bounded(lambda: pm._run_apply("settled", ready=True))
    assert held.taken.wait(_JOIN_S), "автостарт не подан исполнителю"

    operator = _bounded(pm._cmd_system_run_start)
    assert operator["success"] is True, operator

    _bounded(held.run_held)

    assert _texts(pm._log_info).count(_I_ALREADY_RUNNING) == 1, _texts(pm._log_info)
    assert [w for w in _texts(pm._log_warning) if w.startswith(_W_REFUSED_PREFIX)] == [], _texts(pm._log_warning)
    _stay(store, 1, 0.5)
    assert _state(pm) == "running"


# --------------------------------------------------------------------------- #
# S3c 14 — настоящий pm-lifecycle
# --------------------------------------------------------------------------- #


def _lifecycle_wired(pm: ProcessManagerProcess) -> tuple[Any, Any]:
    """Настоящий ``pm-lifecycle`` (образец ``_lifecycle_wired`` из ``test_run_apply_gate``, без ``CommandManager``)."""
    pm._ensure_routing_state()  # ``_routing_lock`` ставит боевой ``__init__``; адаптер исполнителя берёт его
    worker_manager = WorkerManager(manager_name="autostart-hazard", process=None)
    assert worker_manager.initialize() is True
    manager = ExecutorManager("autostart-hazard_executors", worker_manager=worker_manager)
    assert manager.initialize() is True
    pm.executor_manager = manager
    assert pm._setup_lifecycle_executor() is True
    return manager, worker_manager


@pytest.mark.timeout(60)
def test_real_lifecycle_executor_takes_autostart() -> None:
    """14. Boot ``ready`` -> ``running`` 1 раз за 3 с; START выполнен не на обходном потоке ``run-autostart``;
    WARNING/ERROR об отказе исполнителя нет."""
    pm, monitor, store = _pm()
    executor_manager, worker_manager = _lifecycle_wired(pm)
    threads: list[str] = []
    original_start = pm._cmd_system_run_start

    def recording_start(*args: Any, **kwargs: Any) -> dict:
        threads.append(threading.current_thread().name)
        return original_start(*args, **kwargs)

    pm._cmd_system_run_start = recording_start
    try:
        _bounded(lambda: beat(monitor, "cam"))
        _bounded(lambda: pm._run_apply("settled", ready=True))

        assert _wait(lambda: store.starts() >= 1), store.writes
        _stay(store, 1, 0.5)
        assert len(threads) == 1 and threads[0] != "run-autostart", threads
        about_executor = [t for t in _texts(pm._log_warning) + _texts(pm._log_error) if "run-autostart" in t]
        assert about_executor == [], about_executor
        assert _texts(pm._log_warning).count(_W_AUTOSTART) == 1
    finally:
        for stop in (executor_manager.shutdown, worker_manager.shutdown):
            thread = threading.Thread(target=stop, daemon=True)
            thread.start()
            thread.join(10.0)


# --------------------------------------------------------------------------- #
# Гонки
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_concurrent_ticks_fire_once() -> None:
    """20 потоков такта из ``not_ready`` разом (готовность есть) -> ``running`` ровно 1 раз, одна WARNING
    «автостарт: …». Каждый поток — с join-дедлайном."""
    pm, monitor, store = _pm()
    _bounded(lambda: pm._run_apply("settled", ready=False))
    assert _state(pm) == "not_ready"
    _bounded(lambda: beat(monitor, "cam"))
    barrier = threading.Barrier(20)
    errors: list[BaseException] = []

    def one_tick() -> None:
        try:
            barrier.wait(_JOIN_S)
            pm._run_apply("tick", ready=True)
        except BaseException as exc:  # noqa: BLE001 — в поток теста
            errors.append(exc)

    workers = [threading.Thread(target=one_tick, daemon=True, name=f"tick-{i}") for i in range(20)]
    for th in workers:
        th.start()
    for th in workers:
        th.join(_JOIN_S)
    assert [th.name for th in workers if th.is_alive()] == [], "поток такта завис"
    assert errors == [], errors

    assert _wait(lambda: store.starts() >= 1), store.writes
    _stay(store, 1)
    assert _texts(pm._log_warning).count(_W_AUTOSTART) == 1, _texts(pm._log_warning)


@pytest.mark.timeout(60)
@pytest.mark.parametrize("round_no", range(5))
def test_operator_start_races_autostart(round_no: int) -> None:
    """START оператора наперегонки с автостартом (обходной поток): ``running`` ровно 1 раз; WARNING «автостарт
    отказан» нет ни при каком исходе (проигравший получает ``already_running``)."""
    pm, monitor, store = _pm()
    _bounded(lambda: beat(monitor, "cam"))
    replies: list[dict] = []

    def operator() -> None:
        replies.append(pm._cmd_system_run_start())

    settle = threading.Thread(target=lambda: pm._run_apply("settled", ready=True), daemon=True, name="settle")
    op = threading.Thread(target=operator, daemon=True, name="operator")
    settle.start()
    op.start()
    settle.join(_JOIN_S)
    op.join(_JOIN_S)
    assert not settle.is_alive() and not op.is_alive(), "подача зависла"

    assert _wait(lambda: store.starts() >= 1), store.writes
    _stay(store, 1, 0.5)
    assert len(replies) == 1
    assert replies[0].get("success") is True or replies[0].get("error") in ("not_ready", "already_running"), replies
    assert [w for w in _texts(pm._log_warning) if w.startswith(_W_REFUSED_PREFIX)] == [], _texts(pm._log_warning)
