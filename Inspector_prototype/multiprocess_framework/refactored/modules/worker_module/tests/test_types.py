# -*- coding: utf-8 -*-
"""Тесты для types/types.py."""

import threading
import pytest

from ..types import WorkerStatus, ThreadPriority, WorkerType, ExecutionMode, WorkerInfo


class TestWorkerStatus:
    def test_all_values(self):
        values = {s.value for s in WorkerStatus}
        assert values == {"stopped", "running", "error", "stopping", "completed"}

    def test_completed_exists(self):
        assert WorkerStatus.COMPLETED.value == "completed"


class TestThreadPriority:
    def test_ordering(self):
        assert ThreadPriority.SYSTEM.value < ThreadPriority.NORMAL.value
        assert ThreadPriority.NORMAL.value < ThreadPriority.BACKGROUND.value

    def test_all_five(self):
        assert len(ThreadPriority) == 5


class TestWorkerType:
    def test_values(self):
        assert WorkerType.SYSTEM.value == "system"
        assert WorkerType.APPLICATION.value == "application"


class TestExecutionMode:
    def test_values(self):
        assert ExecutionMode.LOOP.value == "loop"
        assert ExecutionMode.TASK.value == "task"


class TestWorkerInfoTypedDict:
    def test_can_construct(self):
        stop = threading.Event()
        pause = threading.Event()
        thread = threading.Thread(target=lambda: None)

        info: WorkerInfo = {
            "thread": thread,
            "stop_event": stop,
            "pause_event": pause,
            "target": lambda s, p: None,
            "config": None,
            "status": WorkerStatus.STOPPED,
            "worker_type": WorkerType.APPLICATION,
            "execution_mode": ExecutionMode.LOOP,
            "restart_count": 0,
            "last_error": None,
            "start_time": None,
            "total_runtime": 0.0,
            "last_run_duration": 0.0,
            "successful_runs": 0,
            "failed_runs": 0,
            "has_been_started": False,
        }
        assert info["status"] == WorkerStatus.STOPPED
        assert info["worker_type"] == WorkerType.APPLICATION
