# -*- coding: utf-8 -*-
"""Тесты для process_module/types/types.py."""

import pickle
import pytest

from ..types import (
    ProcessStatus,
    ManagerType,
    QueueType,
    ProcessConfigDict,
    ProcessStatsDict,
    ProcessMetadataDict,
)


class TestProcessStatus:
    def test_all_values(self):
        values = {s.value for s in ProcessStatus}
        assert values == {
            "initializing",
            "ready",
            "running",
            "stopping",
            "stopped",
            "error",
            "crashed",
            "unresponsive",
            "failed",
        }

    def test_string_comparison(self):
        assert ProcessStatus.RUNNING == "running"
        assert ProcessStatus.READY.value == "ready"

    def test_pickle_safe(self):
        data = pickle.dumps(ProcessStatus.RUNNING)
        restored = pickle.loads(data)
        assert restored == ProcessStatus.RUNNING

    def test_lifecycle_order(self):
        lifecycle = [
            ProcessStatus.INITIALIZING,
            ProcessStatus.READY,
            ProcessStatus.RUNNING,
            ProcessStatus.STOPPING,
            ProcessStatus.STOPPED,
        ]
        assert len(lifecycle) == 5


class TestManagerType:
    def test_all_values(self):
        values = {m.value for m in ManagerType}
        assert values == {"worker", "logger", "command", "router"}

    def test_string_comparison(self):
        assert ManagerType.WORKER == "worker"


class TestQueueType:
    def test_all_values(self):
        values = {q.value for q in QueueType}
        assert "system" in values
        assert "data" in values
        assert "broadcast" in values

    def test_standard_queues(self):
        assert QueueType.SYSTEM.value == "system"
        assert QueueType.DATA.value == "data"
        assert QueueType.COMMANDS.value == "commands"
        assert QueueType.RESULTS.value == "results"


class TestProcessConfigDict:
    def test_can_construct_empty(self):
        config: ProcessConfigDict = {}
        assert config == {}

    def test_can_construct_full(self):
        config: ProcessConfigDict = {
            "process": {"name": "test"},
            "managers": {"logger": {"level": "INFO"}},
            "modules": {},
            "workers": {},
            "custom": {},
        }
        assert config["process"]["name"] == "test"
        assert config["managers"]["logger"]["level"] == "INFO"

    def test_pickle_safe(self):
        config: ProcessConfigDict = {"process": {"name": "test"}, "managers": {}}
        data = pickle.dumps(config)
        restored = pickle.loads(data)
        assert restored["process"]["name"] == "test"


class TestProcessStatsDict:
    def test_can_construct(self):
        stats: ProcessStatsDict = {
            "name": "test_process",
            "running": True,
            "status": ProcessStatus.RUNNING.value,
            "queues": {"system": {"size": 0}},
            "workers": {},
        }
        assert stats["name"] == "test_process"
        assert stats["running"] is True
        assert stats["status"] == "running"
