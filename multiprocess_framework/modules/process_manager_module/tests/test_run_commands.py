# -*- coding: utf-8 -*-
"""Task 1.1 (system-run-state) — слепые тесты держателя состояния работы PM и команд ``system.run.*``.

Контракт — DESIGN п.2 ``plans/2026-10-27_system-run-state/tasks/1.1.md``. Ответы команд — литералы из DESIGN.

PM собирается так же, как в соседних тестах: ``make_pm`` (``__new__`` без ``__init__``) + настоящий
``_create_components()`` под патчем реестра/монитора (как ``test_t54_ready_event_wiring``): событие и ключ ``run_gate``
создаются настоящим кодом PM. «Boot» = то, что делает ``initialize()`` после ``_wait_boot_ready()``:
``_run_apply("settled", ready=True)``.

Решения тестера (ASSUMPTION помечены в тексте):
  * команды вызываются без аргументов: ``pm._cmd_system_run_status()`` (сигнатура как у ``_cmd_system_shutdown``);
  * ключ ``run_gate`` пишется в конфиг фейка ``make_pm`` через ``update_config`` до ``_create_components()``.
"""

from __future__ import annotations

import threading
import time
from typing import Any
from unittest.mock import patch

import pytest

from ..process.process_manager_process import ProcessManagerProcess
from .conftest import make_pm

_PM_MOD = "multiprocess_framework.modules.process_manager_module.process.process_manager_process"
_JOIN_S = 20.0
_ABSENT = object()


def make_run_pm(run_gate: Any = True, *, boot: bool = True) -> ProcessManagerProcess:
    """PM с настоящим ``_create_components()``; ``boot`` — итог ``_wait_boot_ready`` (``settled`` с ready=True)."""
    pm = make_pm()
    if run_gate is not _ABSENT:
        pm.update_config("run_gate", run_gate)
    with (
        patch(f"{_PM_MOD}.ProcessRegistry"),
        patch(f"{_PM_MOD}.ProcessPriority"),
        patch(f"{_PM_MOD}.ProcessStatusMonitor"),
        patch(f"{_PM_MOD}.ProcessMonitor"),
        patch(f"{_PM_MOD}.QueueRegistry"),
    ):
        pm._create_components()
    if boot:
        pm._run_apply("settled", ready=True)
    return pm


class _Store:
    """Двойник стора: журнал записей ``(path, value)``; ``slow_first_s`` — сон первого вызова (окно гонки)."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, Any]] = []
        self.slow_first_s = 0.0
        self.first_entered = threading.Event()
        self._lock = threading.Lock()
        self._calls = 0

    def handle_state_set(self, msg: dict) -> dict:
        data = msg["data"]
        with self._lock:
            self._calls += 1
            first = self._calls == 1
        if first and self.slow_first_s:
            self.first_entered.set()
            time.sleep(self.slow_first_s)
        with self._lock:
            self.writes.append((data["path"], data["value"]))
        return {"status": "ok", "path": data["path"], "changed": True}

    def values(self, path: str) -> list[Any]:
        return [v for p, v in self.writes if p == path]


def _join(thread: threading.Thread) -> None:
    thread.join(_JOIN_S)
    assert not thread.is_alive(), f"поток {thread.name} завис дольше {_JOIN_S} с"


# --------------------------------------------------------------------------- #
# Ответы команд
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
@pytest.mark.parametrize("run_gate", [True, False])
def test_run_command_replies(run_gate: bool) -> None:
    """boot -> status; start; start повторно; stop; stop повторно; затем not_ready и shutting_down (литералы DESIGN)."""
    pm = make_run_pm(run_gate)

    status = pm._cmd_system_run_status()
    assert set(status) == {"state", "since", "run_gate", "start_allowed", "reasons", "last_fault"}, status
    assert status["state"] == "ready"
    assert isinstance(status["since"], float) and status["since"] > 0.0, status["since"]
    assert status["run_gate"] is run_gate
    assert status["start_allowed"] is True
    assert status["reasons"] == []
    assert status["last_fault"] is None

    assert pm._cmd_system_run_start() == {"success": True, "state": "running"}
    assert pm._cmd_system_run_status()["state"] == "running"
    assert pm._cmd_system_run_status()["start_allowed"] is False
    assert pm._cmd_system_run_start() == {
        "success": False,
        "state": "running",
        "error": "already_running",
        "reasons": [],
    }

    assert pm._cmd_system_run_stop() == {"success": True, "accepted": True, "state": "stopping"}
    # внутри вызова stop -> settled: опрос после ответа видит ready
    assert pm._cmd_system_run_status()["state"] == "ready"
    assert pm._cmd_system_run_stop() == {"success": True, "accepted": False, "state": "ready"}

    # not_ready — только через tick(ready=False) до Task 1.3
    pm._run_apply("tick", ready=False)
    status = pm._cmd_system_run_status()
    assert status["state"] == "not_ready" and status["start_allowed"] is False, status
    assert pm._cmd_system_run_start() == {
        "success": False,
        "state": "not_ready",
        "error": "not_ready",
        "reasons": [],
    }
    assert pm._cmd_system_run_stop() == {"success": True, "accepted": False, "state": "not_ready"}

    # подача shutdown в машину — Task 1.4; строка таблицы проверяется прямым _run_apply
    pm._run_apply("shutdown")
    assert pm._cmd_system_run_start() == {
        "success": False,
        "state": "shutting_down",
        "error": "shutting_down",
        "reasons": [],
    }
    assert pm._cmd_system_run_stop() == {"success": False, "state": "shutting_down", "error": "shutting_down"}


# --------------------------------------------------------------------------- #
# Событие следует за состоянием
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
@pytest.mark.parametrize("run_gate", [True, False])
def test_run_gate_event_follows_state(run_gate: bool) -> None:
    """run_gate true: boot снято, start взведено, stop снято (state ready), потеря готовности в running снимает.
    run_gate false: взведено всегда."""
    pm = make_run_pm(run_gate, boot=False)
    event = pm._run_event
    assert event is not None
    assert event.is_set() is (not run_gate), "создание: при run_gate true снято, при false — сразу взведено"

    pm._run_apply("settled", ready=True)
    assert pm._run_state == "ready"
    assert event.is_set() is (not run_gate), "после boot"

    assert pm._cmd_system_run_start()["success"] is True
    assert pm._run_state == "running"
    assert event.is_set() is True, "после start"

    assert pm._cmd_system_run_stop()["accepted"] is True
    assert pm._cmd_system_run_status()["state"] == "ready"
    assert event.is_set() is (not run_gate), "после stop"

    # потеря готовности в running -> fault: при run_gate true событие снято, при false не тронуто
    assert pm._cmd_system_run_start()["success"] is True
    assert event.is_set() is True
    pm._run_apply("tick", ready=False)
    assert pm._run_state == "fault"
    assert event.is_set() is (not run_gate), "после fault"


@pytest.mark.timeout(60)
@pytest.mark.parametrize("run_gate", [False, None, "false", 0, "ZZ-marker-value"])
def test_run_gate_false_stop_never_clears_event(run_gate: Any) -> None:
    """Не-true ``run_gate`` -> машина наблюдаемая, не гейтящая: событие взведено с boot, stop и fault его не снимают."""
    pm = make_run_pm(run_gate)
    event = pm._run_event
    assert event is not None and event.is_set() is True, "после boot событие взведено"
    assert pm._run_gate is False

    assert pm._cmd_system_run_start()["success"] is True
    assert event.is_set() is True
    assert pm._cmd_system_run_stop()["accepted"] is True
    assert event.is_set() is True, "STOP не снимает событие при run_gate != true"
    assert pm._cmd_system_run_start()["success"] is True
    pm._run_apply("tick", ready=False)  # running -> fault
    assert pm._run_state == "fault"
    assert event.is_set() is True, "fault не снимает событие при run_gate != true"
    assert pm._cmd_system_run_status()["run_gate"] is False

    warnings = [str(c.args[0]) for c in pm._log_warning.call_args_list if c.args and "run_gate" in str(c.args[0])]
    if run_gate is False:
        assert warnings == [], warnings  # bool: предупреждать не о чем
    elif run_gate is None:
        # ASSUMPTION: None неотличим от «ключа нет» (get_config даёт None) — одна WARNING допустима, но не больше
        assert len(warnings) <= 1, warnings
    else:
        assert len(warnings) == 1, warnings  # не-bool: ровно одна WARNING за всё время (не на каждый вызов)
        if run_gate == "ZZ-marker-value":
            assert "ZZ-marker-value" not in warnings[0], "WARNING не должна нести значение ключа"


# --------------------------------------------------------------------------- #
# START отказан, пока система гаснет
# --------------------------------------------------------------------------- #


def _trigger_event(pm: ProcessManagerProcess) -> None:
    pm._system_stop_event = threading.Event()
    pm._system_stop_event.set()


def _trigger_children_stopping(pm: ProcessManagerProcess) -> None:
    pm._children_stopping = True


def _trigger_begun_stop(pm: ProcessManagerProcess) -> None:
    assert pm._begin_system_stop("graceful", "t", None, phase="pre_stop") is True


@pytest.mark.timeout(60)
@pytest.mark.parametrize(
    "trigger",
    [_trigger_event, _trigger_children_stopping, _trigger_begun_stop],
    ids=["system_stop_event", "children_stopping", "begun_pre_stop"],
)
def test_start_refused_while_system_stopping(trigger) -> None:
    """Любой из трёх признаков гашения: START -> отказ ``shutting_down``, событие не взведено, running не наступил."""
    pm = make_run_pm(True)
    assert pm._run_event.is_set() is False
    trigger(pm)

    reply = pm._cmd_system_run_start()

    assert reply["success"] is False, reply
    assert reply["error"] == "shutting_down", reply
    assert reply["reasons"] == [], reply
    # ASSUMPTION: DESIGN даёт "state": <состояние> — это либо текущее состояние машины (ready), либо shutting_down
    assert reply["state"] == "ready", reply
    assert pm._run_event.is_set() is False, "событие взведено при гашении системы"
    assert pm._run_state != "running"


# --------------------------------------------------------------------------- #
# Гонки: событие == (state == running)
# --------------------------------------------------------------------------- #


class _SlowEvent:
    """Обёртка над настоящим событием: set()/clear() спят 1 мс (расширяют окно гонки), is_set() без сна."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def set(self) -> None:
        time.sleep(0.001)
        self._inner.set()

    def clear(self) -> None:
        time.sleep(0.001)
        self._inner.clear()

    def is_set(self) -> bool:
        return self._inner.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._inner.wait(timeout)


def _slow_pm() -> ProcessManagerProcess:
    pm = make_run_pm(True, boot=False)
    pm._run_event = _SlowEvent(pm._run_event)
    pm._run_apply("settled", ready=True)
    return pm


def _run_threads(workers: list) -> None:
    """Запустить функции потоками по барьеру; исключения потоков пробрасываются в тест."""
    barrier = threading.Barrier(len(workers))
    errors: list[BaseException] = []

    def wrap(fn):
        def go() -> None:
            try:
                barrier.wait(_JOIN_S)
                fn()
            except BaseException as exc:  # noqa: BLE001 — пробросим в поток теста
                errors.append(exc)

        return go

    threads = [threading.Thread(target=wrap(fn), daemon=True, name=f"run-race-{i}") for i, fn in enumerate(workers)]
    for t in threads:
        t.start()
    for t in threads:
        _join(t)
    assert not errors, errors


@pytest.mark.timeout(120)
def test_start_stop_tick_race_event_matches_state() -> None:
    """Гонка start/stop/tick(ready=False): в конце событие == (state == running); один победитель start;
    из параллельных stop при running ровно один ``accepted``. Наблюдатель под ``_run_lock`` не видит расхождения."""
    # --- 1. восемь START из ready: ровно один успех -------------------------------------------------
    pm = _slow_pm()
    for _ in range(20):
        replies: list[dict] = []
        _run_threads([lambda: replies.append(pm._cmd_system_run_start())] * 8)
        assert sum(1 for r in replies if r["success"]) == 1, replies
        assert all(r["error"] == "already_running" for r in replies if not r["success"]), replies
        assert pm._run_event.is_set() is True and pm._run_state == "running"
        # --- 2. восемь STOP при running: ровно один accepted -----------------------------------------
        stops: list[dict] = []
        _run_threads([lambda: stops.append(pm._cmd_system_run_stop())] * 8)
        assert sum(1 for r in stops if r.get("accepted") is True) == 1, stops
        assert pm._run_state == "ready" and pm._run_event.is_set() is False

    # --- 3. смесь start/stop/tick(False) + наблюдатель под _run_lock ---------------------------------
    for round_no in range(40):
        pm = _slow_pm()
        violations: list[tuple[Any, bool]] = []
        quit_ev = threading.Event()

        def observe() -> None:
            while not quit_ev.is_set():
                with pm._run_lock:
                    state, is_set = pm._run_state, pm._run_event.is_set()
                if is_set != (state == "running"):
                    violations.append((state, is_set))

        watcher = threading.Thread(target=observe, daemon=True, name="run-race-observer")
        watcher.start()
        try:
            kinds = [
                lambda: pm._run_apply("start"),
                lambda: pm._run_apply("stop"),
                lambda: pm._run_apply("tick", ready=False),
            ]
            _run_threads([kinds[i % 3] for i in range(8)])
        finally:
            quit_ev.set()
            _join(watcher)
        assert not violations, f"раунд {round_no}: событие разошлось с состоянием под замком: {violations[:3]}"
        assert pm._run_event.is_set() is (pm._run_state == "running"), (round_no, pm._run_state)


# --------------------------------------------------------------------------- #
# Публикация в стор
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_run_state_published_in_order() -> None:
    """start -> stop пишет ``system.run.state`` "running", затем "ready"; поздний издатель не откатывает значение."""
    pm = make_run_pm(True)
    store = _Store()
    pm._state_store_manager = store

    assert pm._cmd_system_run_start()["success"] is True
    assert pm._cmd_system_run_stop()["accepted"] is True

    states = store.values("system.run.state")
    # ASSUMPTION: каждая запись через _run_apply публикует состояние (DESIGN: «после замка — _publish_run_state()»),
    # поэтому промежуточное "stopping" допустимо; обязательны порядок running -> ready и значение ready в конце.
    assert states in (["running", "stopping", "ready"], ["running", "ready"]), states
    since = store.values("system.run.since")
    assert since and all(isinstance(v, float) for v in since), since
    assert since[-1] == pm._run_since

    # --- hazard: два потока публикуют, фейк спит 5 мс у первого вызова -------------------------------
    pm2 = make_run_pm(True)
    slow = _Store()
    slow.slow_first_s = 0.005
    pm2._state_store_manager = slow
    errors: list[BaseException] = []

    def guarded(fn):
        def go() -> None:
            try:
                fn()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        return go

    a = threading.Thread(target=guarded(lambda: pm2._run_apply("start")), daemon=True, name="pub-a")
    a.start()
    assert slow.first_entered.wait(_JOIN_S), "первый издатель не дошёл до стора"
    b = threading.Thread(target=guarded(lambda: pm2._run_apply("stop")), daemon=True, name="pub-b")
    b.start()
    _join(b)
    _join(a)
    assert not errors, errors

    assert pm2._run_state == "stopping"
    assert slow.values("system.run.state")[-1] == "stopping", slow.writes
    assert slow.values("system.run.since")[-1] == pm2._run_since, slow.writes
