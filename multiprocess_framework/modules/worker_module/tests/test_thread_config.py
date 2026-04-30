# -*- coding: utf-8 -*-
"""Тесты для core/thread_config.py."""

import pytest

from ..core.thread_config import ThreadConfig
from ..types import ThreadPriority, WorkerType, ExecutionMode


class TestThreadConfigDefaults:
    def test_defaults(self):
        cfg = ThreadConfig()
        assert cfg.priority == ThreadPriority.NORMAL
        assert cfg.worker_type == WorkerType.APPLICATION
        assert cfg.execution_mode == ExecutionMode.LOOP
        assert cfg.restart_on_failure is False
        assert cfg.max_restarts == 3
        assert cfg.dependencies == []

    def test_poll_interval_normal(self):
        assert ThreadConfig(priority=ThreadPriority.NORMAL).poll_interval == 0.1

    def test_poll_interval_system(self):
        assert ThreadConfig(priority=ThreadPriority.SYSTEM).poll_interval == 0.001

    def test_poll_interval_background(self):
        assert ThreadConfig(priority=ThreadPriority.BACKGROUND).poll_interval == 5.0


class TestThreadConfigToDict:
    def test_to_dict_keys(self):
        cfg = ThreadConfig()
        d = cfg.to_dict()
        assert set(d.keys()) == {
            "priority", "restart_on_failure", "max_restarts",
            "dependencies", "worker_type", "execution_mode",
        }

    def test_to_dict_values(self):
        cfg = ThreadConfig(
            priority=ThreadPriority.REALTIME,
            worker_type=WorkerType.SYSTEM,
            execution_mode=ExecutionMode.TASK,
            restart_on_failure=True,
            max_restarts=5,
            dependencies=["dep1"],
        )
        d = cfg.to_dict()
        assert d["priority"] == "REALTIME"
        assert d["worker_type"] == "system"
        assert d["execution_mode"] == "task"
        assert d["restart_on_failure"] is True
        assert d["max_restarts"] == 5
        assert d["dependencies"] == ["dep1"]


class TestThreadConfigFromDict:
    def test_roundtrip(self):
        original = ThreadConfig(
            priority=ThreadPriority.BATCH,
            worker_type=WorkerType.SYSTEM,
            execution_mode=ExecutionMode.TASK,
            restart_on_failure=True,
            max_restarts=2,
            dependencies=["a", "b"],
        )
        restored = ThreadConfig.from_dict(original.to_dict())
        assert restored.priority == original.priority
        assert restored.worker_type == original.worker_type
        assert restored.execution_mode == original.execution_mode
        assert restored.restart_on_failure == original.restart_on_failure
        assert restored.max_restarts == original.max_restarts
        assert restored.dependencies == original.dependencies

    def test_from_empty_dict(self):
        cfg = ThreadConfig.from_dict({})
        assert cfg.priority == ThreadPriority.NORMAL
        assert cfg.worker_type == WorkerType.APPLICATION
        assert cfg.execution_mode == ExecutionMode.LOOP

    def test_from_partial_dict(self):
        cfg = ThreadConfig.from_dict({"priority": "SYSTEM", "execution_mode": "task"})
        assert cfg.priority == ThreadPriority.SYSTEM
        assert cfg.execution_mode == ExecutionMode.TASK
        assert cfg.worker_type == WorkerType.APPLICATION
