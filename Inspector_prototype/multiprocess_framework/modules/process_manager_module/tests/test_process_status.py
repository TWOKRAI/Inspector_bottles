"""
Тесты для ProcessStatus.

Проверяют мониторинг статуса процессов.
"""

import time
import pytest
from multiprocessing import Process

from ..core.process_status import ProcessStatus


def _dummy_target() -> None:
    time.sleep(2)


class TestProcessStatus:
    """Тесты ProcessStatus."""

    def test_get_process_status(self) -> None:
        """get_process_status() возвращает статус процесса."""
        process = Process(target=_dummy_target, name="TestProcess")
        status_obj = ProcessStatus([process])

        status = status_obj.get_process_status("TestProcess")

        assert status is not None
        assert status["name"] == "TestProcess"
        assert not status["alive"]
        assert status["pid"] is None

        process.start()
        time.sleep(0.1)
        status = status_obj.get_process_status("TestProcess")
        assert status["alive"]
        assert status["pid"] is not None

        process.terminate()
        process.join(timeout=1.0)

    def test_get_process_status_not_found(self) -> None:
        """get_process_status() для неизвестного возвращает None."""
        status_obj = ProcessStatus([])
        result = status_obj.get_process_status("Unknown")
        assert result is None

    def test_get_all_status(self) -> None:
        """get_all_status() возвращает словарь всех процессов."""
        p1 = Process(target=_dummy_target, name="P1")
        p2 = Process(target=_dummy_target, name="P2")
        status_obj = ProcessStatus([p1, p2])

        all_status = status_obj.get_all_status()

        assert "P1" in all_status
        assert "P2" in all_status
        assert all_status["P1"]["name"] == "P1"

    def test_get_stats(self) -> None:
        """get_stats() возвращает total, alive, dead, alive_percent."""
        process = Process(target=_dummy_target, name="TestProcess")
        status_obj = ProcessStatus([process])

        stats = status_obj.get_stats()

        assert stats["total"] == 1
        assert stats["alive"] == 0
        assert stats["dead"] == 1
        assert "alive_percent" in stats

    def test_get_alive_count(self) -> None:
        """get_alive_count() возвращает количество живых."""
        process = Process(target=_dummy_target, name="TestProcess")
        status_obj = ProcessStatus([process])

        assert status_obj.get_alive_count() == 0

        process.start()
        time.sleep(0.1)
        assert status_obj.get_alive_count() == 1

        process.terminate()
        process.join(timeout=1.0)
