# -*- coding: utf-8 -*-
"""Тесты для registry/worker_registry.py."""

import threading
import time
import pytest

from ..registry.worker_registry import WorkerRegistry
from ..core.thread_config import ThreadConfig
from ..types import WorkerStatus, WorkerType, ExecutionMode


def _make_thread():
    return threading.Thread(target=lambda: None)


def _make_config(worker_type=WorkerType.APPLICATION, execution_mode=ExecutionMode.LOOP):
    cfg = ThreadConfig(worker_type=worker_type, execution_mode=execution_mode)
    return cfg


def _register(registry, name, worker_type=WorkerType.APPLICATION):
    cfg = _make_config(worker_type=worker_type)
    return registry.register(
        name,
        lambda s, p: None,
        cfg,
        _make_thread(),
        threading.Event(),
        threading.Event(),
    )


class TestWorkerRegistryBasic:
    def test_register_and_has(self):
        r = WorkerRegistry()
        assert _register(r, "w1") is True
        assert r.has("w1") is True

    def test_register_duplicate_returns_false(self):
        r = WorkerRegistry()
        _register(r, "w1")
        assert _register(r, "w1") is False

    def test_unregister(self):
        r = WorkerRegistry()
        _register(r, "w1")
        assert r.unregister("w1") is True
        assert r.has("w1") is False

    def test_unregister_missing_returns_false(self):
        r = WorkerRegistry()
        assert r.unregister("missing") is False

    def test_get_returns_dict(self):
        r = WorkerRegistry()
        _register(r, "w1")
        info = r.get("w1")
        assert isinstance(info, dict)
        assert info["status"] == WorkerStatus.STOPPED

    def test_get_missing_returns_none(self):
        r = WorkerRegistry()
        assert r.get("missing") is None

    def test_get_all_names(self):
        r = WorkerRegistry()
        _register(r, "a")
        _register(r, "b")
        names = r.get_all_names()
        assert set(names) == {"a", "b"}

    def test_len(self):
        r = WorkerRegistry()
        _register(r, "x")
        _register(r, "y")
        assert len(r) == 2


class TestWorkerRegistryStatus:
    def test_update_and_get_status(self):
        r = WorkerRegistry()
        _register(r, "w1")
        r.update_status("w1", WorkerStatus.RUNNING)
        assert r.get_status("w1") == WorkerStatus.RUNNING

    def test_update_missing_no_error(self):
        r = WorkerRegistry()
        r.update_status("missing", WorkerStatus.RUNNING)  # должно не падать


class TestWorkerRegistryGetByType:
    def test_get_by_type_application(self):
        r = WorkerRegistry()
        _register(r, "app1", WorkerType.APPLICATION)
        _register(r, "sys1", WorkerType.SYSTEM)
        assert r.get_by_type(WorkerType.APPLICATION) == ["app1"]

    def test_get_by_type_system(self):
        r = WorkerRegistry()
        _register(r, "app1", WorkerType.APPLICATION)
        _register(r, "sys1", WorkerType.SYSTEM)
        assert r.get_by_type(WorkerType.SYSTEM) == ["sys1"]

    def test_get_by_type_empty(self):
        r = WorkerRegistry()
        assert r.get_by_type(WorkerType.SYSTEM) == []


class TestWorkerRegistryThreadSafety:
    def test_concurrent_register(self):
        r = WorkerRegistry()
        errors = []

        def register_worker(name):
            try:
                _register(r, name)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=register_worker, args=(f"w{i}",)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(r) == 50
