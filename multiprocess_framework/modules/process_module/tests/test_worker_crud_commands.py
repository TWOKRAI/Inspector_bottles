# -*- coding: utf-8 -*-
"""Тесты Фазы B (processes-workers-runtime): worker CRUD-команды + IdleWorker + config-спавн.

Покрывает:
- IdleWorker: loop/task, smart-sleep, телеметрия цикла (get_cycle_metrics).
- WorkerManager: remove_worker, is_worker_protected, обогащённый get_worker_status.
- BuiltinCommands: worker.create/remove/update/restart/stop через CommandManager,
  protected-guard (message_processor).
- ProcessLaunchConfig: поле workers → proc_dict["workers"] (config-спавн).
"""

from __future__ import annotations

import threading
import time

from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.process_module.configs.process_launch_config import (
    ProcessLaunchConfig,
)
from multiprocess_framework.modules.process_module.generic.idle_worker import IdleWorker
from multiprocess_framework.modules.worker_module import WorkerManager, WorkerType

_IDLE_PATH = "multiprocess_framework.modules.process_module.generic.idle_worker.IdleWorker"


# ====================================================================== #
#  Фейки для BuiltinCommands                                             #
# ====================================================================== #


class _FakeCommandManager:
    """Минимальный CommandManager: хранит хендлеры, диспатчит по 'command'."""

    def __init__(self) -> None:
        self.handlers: dict = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler

    def dispatch(self, command: str, data: dict | None = None) -> dict:
        return self.handlers[command](data or {})


class _FakeServices:
    """Минимальный IProcessServices для BuiltinCommands worker CRUD."""

    def __init__(self, worker_manager) -> None:
        self.worker_manager = worker_manager
        self.command_manager = _FakeCommandManager()
        self.router_manager = None
        self.name = "test_proc"
        self._current_process_status = "running"

    def _log_info(self, *a, **k) -> None: ...
    def _log_debug(self, *a, **k) -> None: ...
    def _log_warning(self, *a, **k) -> None: ...


def _make_crud():
    """Собрать (worker_manager, command_manager) с зарегистрированными CRUD-командами."""
    wm = WorkerManager("test_wm")
    wm.initialize()
    svc = _FakeServices(wm)
    bc = BuiltinCommands(svc)
    bc._register_worker_crud_commands()
    return wm, svc.command_manager


# ====================================================================== #
#  IdleWorker                                                            #
# ====================================================================== #


class TestIdleWorker:
    def test_idle_worker_loop_cycles_and_metrics(self) -> None:
        """IdleWorker крутит цикл и копит телеметрию (cycles, target_interval_ms)."""
        worker = IdleWorker(config={"target_interval_ms": 20})
        stop = threading.Event()
        pause = threading.Event()
        t = threading.Thread(target=worker.run, args=(stop, pause), daemon=True)
        t.start()
        time.sleep(0.12)
        stop.set()
        t.join(timeout=1.0)

        metrics = worker.get_cycle_metrics()
        assert metrics["cycles"] >= 1
        assert metrics["target_interval_ms"] == 20.0
        assert metrics["effective_hz"] >= 0.0

    def test_idle_worker_task_mode_runs_once(self) -> None:
        """TASK-режим — один проход и выход (run возвращается без stop_event)."""
        worker = IdleWorker(config={"target_interval_ms": 10, "execution_mode": "task"})
        stop = threading.Event()
        pause = threading.Event()
        worker.run(stop, pause)  # не должен зависнуть
        assert worker.get_cycle_metrics()["cycles"] == 1

    def test_idle_worker_default_interval(self) -> None:
        """Без target_interval_ms — дефолт 500 мс."""
        worker = IdleWorker(config={})
        assert worker.get_cycle_metrics()["target_interval_ms"] == 500.0


# ====================================================================== #
#  WorkerManager — remove / protected / status                          #
# ====================================================================== #


class TestWorkerManagerExtensions:
    def test_remove_worker(self) -> None:
        wm = WorkerManager("wm")
        wm.initialize()
        wm.create_worker("w1", IdleWorker(config={}).run, {"priority": "NORMAL"}, auto_start=True)
        assert wm.has_worker("w1")
        assert wm.remove_worker("w1") is True
        assert not wm.has_worker("w1")

    def test_remove_missing_worker_returns_false(self) -> None:
        wm = WorkerManager("wm")
        wm.initialize()
        assert wm.remove_worker("ghost") is False

    def test_is_worker_protected_by_name(self) -> None:
        wm = WorkerManager("wm")
        wm.initialize()
        assert wm.is_worker_protected("message_processor") is True
        assert wm.is_worker_protected("regular") is False

    def test_is_worker_protected_by_system_type(self) -> None:
        wm = WorkerManager("wm")
        wm.initialize()
        wm.create_worker("sysw", IdleWorker(config={}).run, {"priority": "SYSTEM", "worker_type": "system"})
        assert wm.is_worker_protected("sysw") is True

    def test_get_worker_status_enriched(self) -> None:
        """status содержит priority/protected/cycle-метрики IdleWorker."""
        wm = WorkerManager("wm")
        wm.initialize()
        wm.create_worker("w1", IdleWorker(config={"target_interval_ms": 40}).run, {"priority": "REALTIME"})
        status = wm.get_worker_status("w1")
        assert status is not None
        assert status["priority"] == "REALTIME"
        assert status["protected"] is False
        assert "cycle_duration_ms" in status
        assert status["target_interval_ms"] == 40.0


# ====================================================================== #
#  BuiltinCommands worker CRUD                                           #
# ====================================================================== #


class TestWorkerCrudCommands:
    def test_create_worker_via_command(self) -> None:
        wm, cm = _make_crud()
        res = cm.dispatch(
            "worker.create",
            {"worker_name": "grabber", "priority": "REALTIME", "target_interval_ms": 33},
        )
        assert res["success"] is True
        assert wm.has_worker("grabber")
        assert wm.get_worker_status("grabber")["priority"] == "REALTIME"

    def test_create_duplicate_rejected(self) -> None:
        wm, cm = _make_crud()
        cm.dispatch("worker.create", {"worker_name": "w"})
        res = cm.dispatch("worker.create", {"worker_name": "w"})
        assert res["success"] is False
        assert "уже существует" in res["reason"]

    def test_create_missing_name_rejected(self) -> None:
        _wm, cm = _make_crud()
        res = cm.dispatch("worker.create", {})
        assert res["success"] is False

    def test_create_with_explicit_class_path(self) -> None:
        """worker_class dotted-path резолвится (IdleWorker)."""
        wm, cm = _make_crud()
        res = cm.dispatch("worker.create", {"worker_name": "w", "worker_class": _IDLE_PATH})
        assert res["success"] is True
        assert wm.has_worker("w")

    def test_remove_worker_via_command(self) -> None:
        wm, cm = _make_crud()
        cm.dispatch("worker.create", {"worker_name": "w"})
        res = cm.dispatch("worker.remove", {"worker_name": "w"})
        assert res["success"] is True
        assert not wm.has_worker("w")

    def test_remove_protected_blocked(self) -> None:
        """message_processor нельзя удалить через IPC."""
        wm, cm = _make_crud()
        # message_processor создаётся как обычный, но защищён по имени
        wm.create_worker("message_processor", IdleWorker(config={}).run, {"priority": "NORMAL"})
        res = cm.dispatch("worker.remove", {"worker_name": "message_processor"})
        assert res["success"] is False
        assert res["reason"] == "protected"
        assert wm.has_worker("message_processor")

    def test_stop_protected_blocked(self) -> None:
        _wm, cm = _make_crud()
        res = cm.dispatch("worker.stop", {"worker_name": "message_processor"})
        assert res["success"] is False
        assert res["reason"] == "protected"

    def test_restart_worker_via_command(self) -> None:
        wm, cm = _make_crud()
        cm.dispatch("worker.create", {"worker_name": "w", "target_interval_ms": 20})
        res = cm.dispatch("worker.restart", {"worker_name": "w"})
        assert res["success"] is True
        assert wm.has_worker("w")

    def test_update_worker_changes_priority(self) -> None:
        wm, cm = _make_crud()
        cm.dispatch("worker.create", {"worker_name": "w", "priority": "NORMAL"})
        res = cm.dispatch("worker.update", {"worker_name": "w", "priority": "BATCH", "target_interval_ms": 100})
        assert res["success"] is True
        assert wm.has_worker("w")
        assert wm.get_worker_status("w")["priority"] == "BATCH"

    def test_update_protected_blocked(self) -> None:
        _wm, cm = _make_crud()
        res = cm.dispatch("worker.update", {"worker_name": "message_processor", "priority": "BATCH"})
        assert res["success"] is False
        assert res["reason"] == "protected"


# ====================================================================== #
#  ProcessLaunchConfig — config-спавн                                    #
# ====================================================================== #


class TestProcessLaunchConfigWorkers:
    def test_workers_default_empty(self) -> None:
        cfg = ProcessLaunchConfig(process_name="p", process_class="x.Y")
        _name, proc_dict = cfg.build()
        assert proc_dict["workers"] == {}

    def test_workers_flow_to_proc_dict(self) -> None:
        """workers попадает на верхний уровень proc_dict, не в config."""
        workers = {
            "grabber": {
                "class": _IDLE_PATH,
                "config": {"target_interval_ms": 33},
                "thread": {"priority": "REALTIME"},
            }
        }
        cfg = ProcessLaunchConfig(process_name="p", process_class="x.Y", workers=workers)
        _name, proc_dict = cfg.build()
        assert proc_dict["workers"] == workers
        assert "workers" not in proc_dict["config"]

    def test_protected_worker_type_constant(self) -> None:
        """Системный тип защищён независимо от имени."""
        assert WorkerType.SYSTEM.value == "system"
