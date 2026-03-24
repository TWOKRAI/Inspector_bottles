# -*- coding: utf-8 -*-
"""Тесты для lifecycle/worker_lifecycle.py."""

import threading
import time
import pytest

from ..core.thread_config import ThreadConfig
from ..types import WorkerStatus, WorkerType, ExecutionMode, ThreadPriority
from ..registry.worker_registry import WorkerRegistry
from ..lifecycle.worker_lifecycle import WorkerLifecycle


class _FakeManager:
    """Минимальный стаб WorkerManager для тестирования WorkerLifecycle."""

    def __init__(self):
        self.manager_name = "test_process"
        self._worker_registry = WorkerRegistry()
        self._lifecycle = None  # будет установлен снаружи
        self._logs = []

    def _log_info(self, msg):
        self._logs.append(("info", msg))

    def _log_error(self, msg):
        self._logs.append(("error", msg))

    def _log_warning(self, msg):
        self._logs.append(("warning", msg))

    def is_worker_running(self, name):
        info = self._worker_registry.get(name)
        return bool(info and info["status"] == WorkerStatus.RUNNING)


def _make_manager():
    mgr = _FakeManager()
    lifecycle = WorkerLifecycle(mgr)
    mgr._lifecycle = lifecycle
    return mgr, lifecycle


class TestWorkerLifecycleCreate:
    def test_create_basic(self):
        mgr, lc = _make_manager()
        cfg = ThreadConfig()
        assert lc.create_worker("w1", lambda s, p: None, cfg) is True
        assert mgr._worker_registry.has("w1")

    def test_create_duplicate_returns_false(self):
        mgr, lc = _make_manager()
        cfg = ThreadConfig()
        lc.create_worker("w1", lambda s, p: None, cfg)
        assert lc.create_worker("w1", lambda s, p: None, cfg) is False

    def test_create_with_missing_dependency_returns_false(self):
        mgr, lc = _make_manager()
        cfg = ThreadConfig(dependencies=["dep1"])
        assert lc.create_worker("w1", lambda s, p: None, cfg) is False


class TestWorkerLifecycleStartStop:
    def test_start_and_stop(self):
        mgr, lc = _make_manager()
        done = threading.Event()

        def target(stop, pause):
            done.wait(timeout=5)

        cfg = ThreadConfig()
        lc.create_worker("w1", target, cfg)
        lc.start_worker("w1")

        time.sleep(0.05)
        assert mgr._worker_registry.get_status("w1") == WorkerStatus.RUNNING

        done.set()
        lc.stop_worker("w1", timeout=2.0)
        assert mgr._worker_registry.get_status("w1") == WorkerStatus.STOPPED

    def test_start_missing_returns_false(self):
        mgr, lc = _make_manager()
        assert lc.start_worker("missing") is False

    def test_stop_missing_returns_false(self):
        mgr, lc = _make_manager()
        assert lc.stop_worker("missing") is False


class TestWorkerLifecycleExecutionMode:
    def test_task_mode_sets_completed(self):
        mgr, lc = _make_manager()

        def task_target(stop, pause):
            pass  # завершается сразу

        cfg = ThreadConfig(execution_mode=ExecutionMode.TASK)
        lc.create_worker("task1", task_target, cfg)
        lc.start_worker("task1")

        # Ждём завершения потока
        info = mgr._worker_registry.get("task1")
        info["thread"].join(timeout=2.0)

        assert mgr._worker_registry.get_status("task1") == WorkerStatus.COMPLETED

    def test_loop_mode_sets_stopped_on_finish(self):
        mgr, lc = _make_manager()

        def loop_target(stop, pause):
            pass  # завершается сразу (не настоящий цикл)

        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        lc.create_worker("loop1", loop_target, cfg)
        lc.start_worker("loop1")

        info = mgr._worker_registry.get("loop1")
        info["thread"].join(timeout=2.0)

        assert mgr._worker_registry.get_status("loop1") == WorkerStatus.STOPPED


class TestWorkerLifecycleAutoRestart:
    def test_auto_restart_on_failure(self):
        mgr, lc = _make_manager()
        call_count = [0]

        def failing_target(stop, pause):
            call_count[0] += 1
            if call_count[0] <= 1:
                raise RuntimeError("intentional error")

        cfg = ThreadConfig(restart_on_failure=True, max_restarts=2)
        lc.create_worker("w1", failing_target, cfg)
        lc.start_worker("w1")

        # Ждём перезапуска
        time.sleep(0.5)
        assert call_count[0] >= 2
