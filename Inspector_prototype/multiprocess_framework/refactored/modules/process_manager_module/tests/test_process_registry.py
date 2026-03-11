"""
Тесты для ProcessRegistry.

Проверяют реестр процессов: add, get, start_all, stop_all.
"""

import time
import pytest
from multiprocessing import Process, Event

from ..core.process_registry import ProcessRegistry


def _dummy_target() -> None:
    """Простая функция-цель для процесса."""
    time.sleep(2)


class TestProcessRegistry:
    """Тесты ProcessRegistry."""

    def test_add_process(self) -> None:
        """add_process() добавляет процесс в os_processes."""
        stop_event = Event()
        registry = ProcessRegistry(stop_event, logger=None)

        process = Process(target=_dummy_target, name="TestProcess")
        registry.add_process(process)

        assert len(registry.os_processes) == 1
        assert process in registry.os_processes

    def test_get_process_by_name(self) -> None:
        """get_process_by_name() возвращает процесс по имени."""
        stop_event = Event()
        registry = ProcessRegistry(stop_event, logger=None)

        process = Process(target=_dummy_target, name="TestProcess")
        registry.add_process(process)

        found = registry.get_process_by_name("TestProcess")
        assert found is process

        not_found = registry.get_process_by_name("Unknown")
        assert not_found is None

    def test_start_all(self) -> None:
        """start_all() запускает все процессы."""
        stop_event = Event()
        registry = ProcessRegistry(stop_event, logger=None)

        process = Process(target=_dummy_target, name="TestProcess")
        registry.add_process(process)

        registry.start_all()
        time.sleep(0.1)

        assert process.is_alive()

        process.terminate()
        process.join(timeout=1.0)

    def test_stop_all(self) -> None:
        """stop_all() останавливает все процессы."""
        stop_event = Event()
        registry = ProcessRegistry(stop_event, logger=None)

        process = Process(target=_dummy_target, name="TestProcess")
        registry.add_process(process)
        process.start()
        time.sleep(0.1)

        registry.stop_all(timeout=1.0)

        assert not process.is_alive()

        process.join(timeout=0.5)
