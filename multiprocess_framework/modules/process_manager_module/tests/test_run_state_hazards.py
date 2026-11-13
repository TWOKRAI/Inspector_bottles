# -*- coding: utf-8 -*-
"""Task 1.3 (system-run-state) — hazard-тесты автора: агрегат готовности PM.

Слепой набор (``test_run_state.py`` / ``test_run_commands.py``) закрывает приёмку по REDS; здесь то, чего он не видит:
гонки и замки (оценка вне ``_run_lock`` и вне замка монитора), мёртвый процесс, ``check_function`` против
``out_of_spec``/``maintenance``, публикация в стор, ``booting -> ready/not_ready`` в ``initialize()``,
``apply -> booting``, непрерывность и липкость ``fault``, реальный цикл монитора.

Стенд — настоящие ``ProcessManagerProcess`` и ``ProcessMonitor`` (``make_readiness_pm``). Всё блокирующее — в
daemon-потоке с join-дедлайном. Ожидаемые значения — литералы.
"""

from __future__ import annotations

import threading
import time
from multiprocessing import Event
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ..process import process_manager_process as pm_mod
from ..process.process_manager_process import ProcessManagerProcess
from .test_run_commands import (
    _PM_MOD,
    _failure_nodes,
    _join,
    _reason,
    _run_threads,
    _Store,
    _to_running,
    beat,
    make_readiness_pm,
    tick,
)

_CAM = {"cam": {"class": "pkg.Cam"}}


def _kill(pm: ProcessManagerProcess, name: str) -> None:
    """Процесс ``name`` в реестре PM перестаёт быть живым."""
    pm._process_registry._processes[name]._alive = False


# --------------------------------------------------------------------------- #
# Замки и потоки
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_evaluation_takes_neither_run_lock_nor_monitor_lock() -> None:
    """Оценка не берёт ``_run_lock`` (``system.run.start`` идёт на message_processor, DECISIONS.md:125) и зовёт
    ``evaluate`` вне замка листов монитора: пока тест держит ``_run_lock``, оценка завершается, а внутри
    ``evaluate`` замок монитора свободен."""
    pm, monitor = make_readiness_pm(_CAM)
    beat(monitor, "cam")
    seen: dict[str, Any] = {}
    real_evaluate = pm_mod.evaluate

    def spying_evaluate(*args: Any, **kwargs: Any) -> Any:
        got = monitor._readiness_lock.acquire(blocking=False)
        seen["monitor_lock_free"] = got
        if got:
            monitor._readiness_lock.release()
        return real_evaluate(*args, **kwargs)

    box: dict[str, Any] = {}

    def run() -> None:
        box["result"] = pm._evaluate_run_readiness()

    with patch.object(pm_mod, "evaluate", spying_evaluate), pm._run_lock:
        worker = threading.Thread(target=run, daemon=True, name="eval-under-run-lock")
        worker.start()
        _join(worker)

    assert box["result"] == (True, [])
    assert seen["monitor_lock_free"] is True, "evaluate вызван под замком листов монитора"


@pytest.mark.timeout(120)
def test_ticks_beats_and_starts_race_keep_event_equal_state() -> None:
    """Такты, heartbeat-ы (свежие и протухшие) и START/STOP идут вперемешку из разных потоков: событие
    ``run_event`` == ``(state == running)`` под ``_run_lock`` в каждый момент, ни один такт не сообщил об ошибке."""
    for round_no in range(15):
        pm, monitor = make_readiness_pm(_CAM)
        beat(monitor, "cam")
        violations: list[tuple[Any, bool]] = []
        quit_ev = threading.Event()

        def observe() -> None:
            while not quit_ev.is_set():
                with pm._run_lock:
                    state, is_set = pm._run_state, pm._run_event.is_set()
                if is_set != (state == "running"):
                    violations.append((state, is_set))

        watcher = threading.Thread(target=observe, daemon=True, name="hazard-observer")
        watcher.start()

        def ticker() -> None:
            for _ in range(20):
                with monitor._iteration_lock:
                    monitor._run_iteration()

        def beater() -> None:
            for i in range(20):
                beat(monitor, "cam", age_s=0.0 if i % 3 else 3600.0)

        def commander() -> None:
            for _ in range(10):
                pm._cmd_system_run_start()
                pm._cmd_system_run_stop()

        try:
            _run_threads([ticker, ticker, beater, commander])
        finally:
            quit_ev.set()
            _join(watcher)
        assert not violations, f"раунд {round_no}: {violations[:3]}"
        assert pm._run_event.is_set() is (pm._run_state == "running"), (round_no, pm._run_state)
        errors = [c.args[0] for c in pm._log_error.call_args_list if c.args]
        assert errors == [], errors


@pytest.mark.timeout(60)
def test_reentrant_tick_while_first_tick_is_publishing() -> None:
    """Повторный вход: первый такт застрял в медленном сторе, второй идёт параллельно — оба завершаются,
    состояние и последняя запись ``system.run.state`` согласованы."""
    pm, monitor = make_readiness_pm(_CAM)
    store = _Store()
    store.slow_first_s = 0.3
    pm._state_store_manager = store
    beat(monitor, "cam")
    pm._run_readiness_tick()  # ready -> ready; первая публикация медленная, но в этом потоке
    store.writes.clear()
    beat(monitor, "cam", ready=False, reasons=[_reason("failure", "cam")])
    _run_threads([pm._run_readiness_tick, pm._run_readiness_tick, pm._run_readiness_tick])
    assert pm._run_state == "not_ready"
    assert store.values("system.run.state")[-1] == "not_ready", store.writes


@pytest.mark.timeout(60)
def test_monitor_loop_thread_drives_fault() -> None:
    """Настоящий цикл монитора (``_monitoring_loop`` в daemon-потоке) сам ведёт ``running -> fault`` при
    протухшем снимке: без ручного такта, за секунды."""
    pm, monitor = make_readiness_pm(_CAM)
    beat(monitor, "cam")
    assert pm._cmd_system_run_start() == {"success": True, "state": "running"}
    stop_ev, pause_ev = threading.Event(), threading.Event()
    monitor._monitoring = True
    loop = threading.Thread(target=monitor._monitoring_loop, args=(stop_ev, pause_ev), daemon=True, name="hz-loop")
    loop.start()
    try:
        beat(monitor, "cam", age_s=3600.0)  # снимок остановился, heartbeat идёт
        deadline = time.monotonic() + 10.0
        while pm._run_state != "fault" and time.monotonic() < deadline:
            time.sleep(0.02)
        assert pm._run_state == "fault", "цикл монитора не довёл running до fault"
    finally:
        stop_ev.set()
        _join(loop)
    assert pm._run_event.is_set() is False
    assert _failure_nodes(pm._cmd_system_run_status()["last_fault"]["reasons"]) == ["cam"]


# --------------------------------------------------------------------------- #
# Живость, check_function, out_of_spec / maintenance
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_dead_process_blocks_start_and_faults_running() -> None:
    """Свежий отчёт ``ready: true``, но процесс не жив: START отказан, причина ``failure`` / ``liveness`` по узлу;
    в ``running`` смерть процесса ведёт в ``fault`` с ``node`` = имя процесса."""
    pm, monitor = make_readiness_pm(_CAM)
    beat(monitor, "cam")
    _kill(pm, "cam")
    reply = pm._cmd_system_run_start()
    assert reply["success"] is False and reply["error"] == "not_ready", reply
    assert _failure_nodes(reply["reasons"]) == ["cam"] and reply["reasons"][0]["source"] == "liveness", reply

    pm2, monitor2 = make_readiness_pm(_CAM)
    _to_running(pm2, monitor2)
    _kill(pm2, "cam")
    beat(monitor2, "cam")  # отчёт свежий — гасит только смерть
    pm2._run_readiness_tick()
    assert pm2._run_state == "fault"
    assert _failure_nodes(pm2._cmd_system_run_status()["last_fault"]["reasons"]) == ["cam"]


@pytest.mark.timeout(60)
def test_check_function_blocks_start_and_running() -> None:
    """``check_function`` при ``ready: true`` в отчёте (К3): блокирует START; в ``running`` равен потере готовности."""
    check = [_reason("check_function", "cam")]
    pm, monitor = make_readiness_pm(_CAM)
    beat(monitor, "cam", ready=True, reasons=check)
    reply = pm._cmd_system_run_start()
    assert reply["success"] is False and reply["error"] == "not_ready", reply
    assert [r["severity"] for r in reply["reasons"]] == ["check_function"], reply

    pm2, monitor2 = make_readiness_pm(_CAM)
    _to_running(pm2, monitor2)
    beat(monitor2, "cam", ready=True, reasons=check)
    tick(pm2, monitor2)
    assert pm2._run_state == "fault"
    assert pm2._run_event.is_set() is False


@pytest.mark.timeout(60)
def test_out_of_spec_and_maintenance_do_not_block() -> None:
    """``out_of_spec`` и ``maintenance`` не блокируют START и не роняют ``running``; причины видны в status."""
    soft = [_reason("out_of_spec", "cam"), _reason("maintenance", "cam")]
    pm, monitor = make_readiness_pm(_CAM)
    beat(monitor, "cam", ready=True, reasons=soft)
    tick(pm, monitor)
    assert pm._run_state == "ready"
    assert pm._cmd_system_run_start() == {"success": True, "state": "running"}
    beat(monitor, "cam", ready=True, reasons=soft)
    tick(pm, monitor)
    assert pm._run_state == "running"
    assert pm._run_event.is_set() is True
    status = pm._cmd_system_run_status()
    assert [r["severity"] for r in status["reasons"]] == ["out_of_spec", "maintenance"], status


@pytest.mark.timeout(60)
def test_tick_skipped_while_system_stops() -> None:
    """Системный стоп: дети молчат, но это не авария работы — такт пропущен, ``running`` остаётся."""
    pm, monitor = make_readiness_pm(_CAM)
    _to_running(pm, monitor)
    pm._children_stopping = True
    beat(monitor, "cam", age_s=3600.0)
    tick(pm, monitor)
    assert pm._run_state == "running"
    assert pm._run_event.is_set() is True


@pytest.mark.timeout(60)
def test_forgotten_process_loses_its_report() -> None:
    """``forget_process`` (switch/cleanup) снимает лист: новое воплощение не наследует отчёт прежнего."""
    pm, monitor = make_readiness_pm(_CAM)
    beat(monitor, "cam")
    assert pm._evaluate_run_readiness() == (True, [])
    monitor.forget_process("cam")
    ready, reasons = pm._evaluate_run_readiness()
    assert ready is False and _failure_nodes(reasons) == ["cam"] and reasons[0]["source"] == "liveness"


@pytest.mark.timeout(60)
def test_stale_s_follows_heartbeat_interval_keys() -> None:
    """``stale_s`` = 3 x наибольший положительный из двух ключей интервала heartbeat; по умолчанию 15."""
    pm, _monitor = make_readiness_pm(_CAM)
    assert pm._run_stale_s() == 15.0  # оба ключа 5.0
    pm.update_config("heartbeat_interval", 2.0)
    pm.update_config("heartbeat_interval_sec", 10.0)
    assert pm._run_stale_s() == 30.0
    pm.update_config("heartbeat_interval", "junk")
    pm.update_config("heartbeat_interval_sec", 0)
    assert pm._run_stale_s() == 15.0  # негодные значения не учитываются: умолчание 5.0 с


# --------------------------------------------------------------------------- #
# Публикация в стор
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_readiness_leaf_published_and_deduplicated() -> None:
    """Лист ``processes.<n>.readiness.*`` пишется в стор; тот же снимок — без повторной записи; сменился один
    ``at`` — переписан только он. Без стора такт работает (гейт от стора не зависит)."""
    pm, monitor = make_readiness_pm(_CAM)
    store = _Store()
    pm._state_store_manager = store
    beat(monitor, "cam")
    monitor._readiness["cam"]["at"] = 100.0  # литерал для сравнения

    pm._run_readiness_tick()
    base = "processes.cam.readiness."
    assert store.values(base + "ready") == [True]
    assert store.values(base + "reasons") == [[]]
    assert store.values(base + "paused") == [False]
    assert store.values(base + "at") == [100.0]

    pm._run_readiness_tick()
    assert len([w for w in store.writes if w[0].startswith(base)]) == 4, store.writes

    monitor._readiness["cam"] = {**monitor._readiness["cam"], "at": 101.0}
    pm._run_readiness_tick()
    assert store.values(base + "at") == [100.0, 101.0]
    assert store.values(base + "ready") == [True]

    pm2, monitor2 = make_readiness_pm(_CAM)  # стора нет
    beat(monitor2, "cam")
    pm2._run_readiness_tick()
    assert pm2._run_state == "ready"


@pytest.mark.timeout(60)
def test_run_reasons_start_allowed_last_fault_published() -> None:
    """``system.run.reasons`` / ``start_allowed`` / ``last_fault`` уходят в стор и совпадают с ``system.run.status``."""
    pm, monitor = make_readiness_pm(_CAM)
    store = _Store()
    pm._state_store_manager = store

    tick(pm, monitor)  # cam молчит -> not_ready
    assert pm._run_state == "not_ready"
    assert store.values("system.run.start_allowed")[-1] is False
    assert _failure_nodes(store.values("system.run.reasons")[-1]) == ["cam"]
    assert store.values("system.run.last_fault")[-1] is None

    beat(monitor, "cam")
    tick(pm, monitor)
    assert store.values("system.run.start_allowed")[-1] is True
    assert store.values("system.run.reasons")[-1] == []
    assert pm._cmd_system_run_start()["success"] is True

    beat(monitor, "cam", ready=False, reasons=[_reason("failure", "cam")])
    tick(pm, monitor)
    assert pm._run_state == "fault"
    published = store.values("system.run.last_fault")[-1]
    assert published is not None and _failure_nodes(published["reasons"]) == ["cam"], published
    assert published == pm._cmd_system_run_status()["last_fault"]
    assert store.values("system.run.state")[-1] == "fault"
    assert store.values("system.run.start_allowed")[-1] is False


@pytest.mark.timeout(60)
def test_status_returns_copies() -> None:
    """Мутация ответа ``system.run.status`` не меняет состояние машины."""
    pm, monitor = make_readiness_pm(_CAM)
    tick(pm, monitor)
    status = pm._cmd_system_run_status()
    status["reasons"].clear()
    status["reasons"].append({"junk": 1})
    assert _failure_nodes(pm._cmd_system_run_status()["reasons"]) == ["cam"]


# --------------------------------------------------------------------------- #
# fault: непрерывность и липкость
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_fault_keeps_first_last_fault_and_refuses_start_with_its_reasons() -> None:
    """В ``fault`` следующие такты (другие причины, возврат готовности) ``last_fault`` не перезаписывают;
    START отказан ``fault_unacknowledged`` с причинами именно ``last_fault``."""
    pm, monitor = make_readiness_pm({"cam": {"class": "pkg.Cam"}, "rec": {"class": "pkg.Rec"}})
    beat(monitor, "cam")
    beat(monitor, "rec")
    tick(pm, monitor)
    assert pm._cmd_system_run_start()["success"] is True
    beat(monitor, "cam", ready=False, reasons=[_reason("failure", "cam")])
    beat(monitor, "rec")
    tick(pm, monitor)
    first = pm._cmd_system_run_status()["last_fault"]
    assert pm._run_state == "fault" and _failure_nodes(first["reasons"]) == ["cam"]

    beat(monitor, "cam", ready=False, reasons=[_reason("failure", "cam")])
    beat(monitor, "rec", ready=False, reasons=[_reason("failure", "rec")])
    tick(pm, monitor)
    beat(monitor, "cam")
    beat(monitor, "rec")
    tick(pm, monitor)

    assert pm._cmd_system_run_status()["last_fault"] == first
    reply = pm._cmd_system_run_start()
    assert reply["error"] == "fault_unacknowledged" and reply["state"] == "fault", reply
    assert _failure_nodes(reply["reasons"]) == ["cam"], reply
    assert pm._run_event.is_set() is False


@pytest.mark.timeout(60)
def test_fault_without_gate_does_not_touch_event() -> None:
    """``run_gate`` false: событие взведено всегда; ``fault`` его не снимает (машина наблюдаемая, не гейтящая)."""
    pm, monitor = make_readiness_pm(_CAM, run_gate=False)
    assert pm._run_event.is_set() is True
    beat(monitor, "cam")
    tick(pm, monitor)
    assert pm._cmd_system_run_start()["success"] is True
    beat(monitor, "cam", ready=False, reasons=[_reason("failure", "cam")])
    tick(pm, monitor)
    assert pm._run_state == "fault"
    assert pm._run_event.is_set() is True


# --------------------------------------------------------------------------- #
# booting -> ready/not_ready: initialize() и topology.apply
# --------------------------------------------------------------------------- #


def _initialize_bare_pm(configs: dict[str, dict]) -> ProcessManagerProcess:
    """Настоящий ``initialize()`` PM из ``__new__`` (образец ``test_process_manager_process``): шаги вне агрегата
    подменены, состояние и событие ставит настоящий ``_create_components()``; ``_process_configs`` задан заранее."""
    pm = ProcessManagerProcess.__new__(ProcessManagerProcess)
    pm.name = "ProcessManager"
    pm.shared_resources = None
    pm.config = {}
    pm.command_manager = MagicMock()
    pm.router_manager = MagicMock()
    pm._system_ready_event = Event()
    pm._backend_ctl_channel = None
    pm._process_configs = dict(configs)
    with (
        patch(f"{_PM_MOD}.ProcessRegistry"),
        patch(f"{_PM_MOD}.ProcessPriority"),
        patch(f"{_PM_MOD}.ProcessStatusMonitor"),
        patch(f"{_PM_MOD}.ProcessMonitor"),
        patch(f"{_PM_MOD}.QueueRegistry"),
        patch.object(ProcessManagerProcess, "get_config", return_value=None),
    ):
        pm._create_components()
    return pm


@pytest.mark.timeout(60)
@pytest.mark.parametrize(
    ("configs", "reported", "expected_state", "expected_nodes"),
    [
        pytest.param({}, False, "ready", [], id="empty-topology"),
        pytest.param(_CAM, False, "not_ready", ["cam"], id="silent-process"),
        pytest.param(_CAM, True, "ready", [], id="reported-process"),
    ],
)
def test_initialize_settles_by_evaluation(configs, reported, expected_state, expected_nodes) -> None:
    """Конец ``initialize()``: ``booting`` -> ``ready``/``not_ready`` по оценке агрегата, а не безусловно ``ready``."""
    pm = _initialize_bare_pm(configs)
    assert pm._run_state == "booting"
    # реестр/монитор настоящие по смыслу: процесс жив, отчёт (если есть) свежий
    registry = MagicMock()
    registry.get_process_by_name.side_effect = lambda n: MagicMock(is_alive=MagicMock(return_value=True))
    pm._process_registry = registry
    monitor = MagicMock()
    now = time.time()
    leaves = {"cam": {"ready": True, "reasons": [], "paused": False, "at": now}} if reported else {}
    monitor.readiness_snapshot.return_value = leaves
    pm._process_monitor = monitor

    with (
        patch.object(ProcessManagerProcess, "get_config", return_value=None),
        patch.object(pm_mod.ProcessModule, "initialize", return_value=True),
        patch.object(ProcessManagerProcess, "_setup_lifecycle_executor", return_value=True),
        patch.object(ProcessManagerProcess, "_setup_console_manager"),
        patch.object(ProcessManagerProcess, "_setup_topology_manager"),
        patch.object(ProcessManagerProcess, "_setup_state_store"),
        patch.object(ProcessManagerProcess, "_register_builtin_commands"),
        patch.object(ProcessManagerProcess, "_log_active_feature_flags"),
        patch.object(ProcessManagerProcess, "_wait_boot_ready"),
        patch.object(ProcessManagerProcess, "_log_info"),
        patch.object(ProcessManagerProcess, "_log_warning"),
        patch.object(ProcessManagerProcess, "_log_error"),
        patch(f"{_PM_MOD}.setup_backend_ctl_channel", return_value=None),
    ):
        assert pm.initialize() is True

    status = pm._cmd_system_run_status()
    assert status["state"] == expected_state, status
    assert _failure_nodes(status["reasons"]) == expected_nodes, status
    assert status["start_allowed"] is (expected_state == "ready")


@pytest.mark.timeout(60)
@pytest.mark.parametrize("apply_outcome", ["success", "failure", "raises"])
def test_apply_goes_booting_then_settles_by_evaluation(apply_outcome: str) -> None:
    """``topology.apply``: на время применения ``booting``; после — по оценке (молчащий процесс -> ``not_ready``),
    при любом исходе, включая исключение: состояние не застревает в ``booting``."""
    pm, monitor = make_readiness_pm(_CAM)
    beat(monitor, "cam")
    tick(pm, monitor)
    assert pm._run_state == "ready"
    during: list[Any] = []

    def fake_apply(blueprint: Any) -> dict:
        during.append(pm._run_state)
        monitor._readiness.clear()  # пересозданный процесс ещё не отчитался
        if apply_outcome == "raises":
            raise RuntimeError("boom")
        return {"success": apply_outcome == "success"}

    with (
        patch.object(pm, "apply_topology", fake_apply),
        patch.object(pm, "_retarget_recipe_address", return_value=""),
        patch.object(pm, "_observability_recipe_address", return_value=""),
    ):
        if apply_outcome == "raises":
            with pytest.raises(RuntimeError):
                pm._cmd_topology_apply({"topology_dict": {}})
        else:
            pm._cmd_topology_apply({"topology_dict": {}})

    assert during == ["booting"]
    assert pm._run_state == "not_ready"
    assert _failure_nodes(pm._cmd_system_run_status()["reasons"]) == ["cam"]


@pytest.mark.timeout(60)
def test_apply_rejected_by_debounce_leaves_state_alone() -> None:
    """Отказ debounce не должен гнать машину в ``booting`` (замены не было)."""
    pm, monitor = make_readiness_pm(_CAM)
    beat(monitor, "cam")
    tick(pm, monitor)
    pm._replace_in_progress = True
    reply = pm._cmd_topology_apply({"topology_dict": {}})
    assert reply["debounced"] is True
    assert pm._run_state == "ready"


@pytest.mark.timeout(60)
def test_run_required_false_excludes_only_literal_false() -> None:
    """Только литерал ``False`` исключает процесс из набора; прочие значения оставляют его обязательным."""
    configs = {
        "a": {"class": "x", "run_required": False},
        "b": {"class": "x", "run_required": "false"},
        "c": {"class": "x", "run_required": None},
        "d": {"class": "x"},
    }
    pm, _monitor = make_readiness_pm(configs)
    assert pm._run_expected_names() == ["b", "c", "d"]
