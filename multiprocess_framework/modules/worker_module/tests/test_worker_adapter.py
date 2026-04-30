# -*- coding: utf-8 -*-
"""Тесты для adapters/worker_adapter.py."""

import threading
import pytest
from unittest.mock import MagicMock, patch

from ..adapters.worker_adapter import WorkerAdapter
from ..core.thread_config import ThreadConfig
from ..types import WorkerType, ExecutionMode, ThreadPriority


class _FakeWorkerManager:
    """Минимальный стаб WorkerManager для тестирования WorkerAdapter."""

    def __init__(self):
        self.created = {}
        self.started = []
        self.stopped = []

    def create_worker(self, name, target, config, auto_start=False):
        self.created[name] = {"target": target, "config": config, "auto_start": auto_start}
        return True

    def start_worker(self, name):
        self.started.append(name)
        return True

    def stop_worker(self, name, timeout=5.0):
        self.stopped.append(name)
        return True

    def restart_worker(self, name, timeout=5.0):
        return True

    def pause_worker(self, name):
        return True

    def resume_worker(self, name):
        return True

    def get_worker_status(self, name):
        return {"name": name, "status": "stopped"}

    def is_worker_running(self, name):
        return False

    def has_worker(self, name):
        return name in self.created

    def list_workers(self, worker_type=None):
        if worker_type is None:
            return list(self.created.keys())
        return [n for n, d in self.created.items()
                if d["config"].worker_type == worker_type]

    def get_stats(self):
        return {"workers_count": len(self.created)}


class TestWorkerAdapterSetup:
    def test_setup_success(self):
        mgr = _FakeWorkerManager()
        adapter = WorkerAdapter(mgr)
        assert adapter.setup() is True
        assert adapter.is_initialized() is True

    def test_setup_no_manager(self):
        adapter = WorkerAdapter(None)
        assert adapter.setup() is False
        assert adapter.is_initialized() is False


class TestWorkerAdapterCreateWorker:
    def test_create_with_default_config(self):
        mgr = _FakeWorkerManager()
        adapter = WorkerAdapter(mgr)
        adapter.setup()

        result = adapter.create_worker("w1", lambda s, p: None)
        assert result is True
        assert "w1" in mgr.created
        cfg = mgr.created["w1"]["config"]
        assert isinstance(cfg, ThreadConfig)

    def test_create_system_worker(self):
        mgr = _FakeWorkerManager()
        adapter = WorkerAdapter(mgr)
        adapter.setup()

        adapter.create_system_worker("sys1", lambda s, p: None)
        cfg = mgr.created["sys1"]["config"]
        assert cfg.worker_type == WorkerType.SYSTEM
        assert cfg.priority == ThreadPriority.SYSTEM

    def test_create_task_worker(self):
        mgr = _FakeWorkerManager()
        adapter = WorkerAdapter(mgr)
        adapter.setup()

        adapter.create_task_worker("task1", lambda s, p: None)
        cfg = mgr.created["task1"]["config"]
        assert cfg.execution_mode == ExecutionMode.TASK


class TestWorkerAdapterDelegation:
    def setup_method(self):
        self.mgr = _FakeWorkerManager()
        self.adapter = WorkerAdapter(self.mgr)
        self.adapter.setup()

    def test_start_worker(self):
        self.adapter.start_worker("w1")
        assert "w1" in self.mgr.started

    def test_stop_worker(self):
        self.adapter.stop_worker("w1")
        assert "w1" in self.mgr.stopped

    def test_list_workers(self):
        self.mgr.create_worker("a", lambda s, p: None, ThreadConfig(), False)
        result = self.adapter.list_workers()
        assert "a" in result

    def test_list_application_workers(self):
        self.mgr.create_worker("app1", lambda s, p: None, ThreadConfig(worker_type=WorkerType.APPLICATION), False)
        result = self.adapter.list_application_workers()
        assert "app1" in result

    def test_get_stats(self):
        stats = self.adapter.get_stats()
        assert "manager" in stats
        assert "adapter_name" in stats
