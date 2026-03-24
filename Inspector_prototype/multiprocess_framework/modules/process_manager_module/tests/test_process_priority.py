"""
Тесты для ProcessPriority.

Проверяют управление приоритетами процессов.
"""

import time
import pytest
from multiprocessing import Process

from ..core.process_priority import ProcessPriority


def _dummy_target() -> None:
    time.sleep(2)


class TestProcessPriority:
    """Тесты ProcessPriority."""

    def test_register_priority(self) -> None:
        """register_priority() сохраняет приоритет."""
        priority = ProcessPriority()
        priority.register_priority("TestProcess", "high")

        assert priority.get_priority("TestProcess") == "high"

    def test_get_priority_default(self) -> None:
        """get_priority() возвращает default для неизвестного процесса."""
        priority = ProcessPriority()
        result = priority.get_priority("UnknownProcess", default="normal")

        assert result == "normal"

    def test_apply_priority_returns_bool(self) -> None:
        """apply_priority() возвращает bool (StubPlatform возвращает False)."""
        priority = ProcessPriority()
        priority.register_priority("TestProcess", "normal")

        process = Process(target=_dummy_target, name="TestProcess")
        process.start()
        time.sleep(0.05)

        result = priority.apply_priority(process, delay=0.01)

        assert isinstance(result, bool)

        process.terminate()
        process.join(timeout=1.0)

    def test_priority_with_logger(self) -> None:
        """ProcessPriority с logger работает."""
        logger = type("MockLogger", (), {"_log_info": lambda *a, **k: None, "_log_warning": lambda *a, **k: None})()
        priority = ProcessPriority(logger=logger)
        priority.register_priority("TestProcess", "high")

        assert priority.get_priority("TestProcess") == "high"
