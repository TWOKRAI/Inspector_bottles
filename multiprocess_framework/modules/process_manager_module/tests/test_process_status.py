"""
Тесты для ProcessStatusMonitor.

Проверяют мониторинг статуса процессов.
"""

import time
from multiprocessing import Process

from ..core.process_status import ProcessStatusMonitor


def _dummy_target() -> None:
    time.sleep(2)


class TestProcessStatusMonitor:
    """Тесты ProcessStatusMonitor."""

    def test_get_process_status(self) -> None:
        """get_process_status() возвращает статус процесса."""
        process = Process(target=_dummy_target, name="TestProcess")
        status_obj = ProcessStatusMonitor([process])

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
        status_obj = ProcessStatusMonitor([])
        result = status_obj.get_process_status("Unknown")
        assert result is None

    def test_get_all_status(self) -> None:
        """get_all_status() возвращает словарь всех процессов."""
        p1 = Process(target=_dummy_target, name="P1")
        p2 = Process(target=_dummy_target, name="P2")
        status_obj = ProcessStatusMonitor([p1, p2])

        all_status = status_obj.get_all_status()

        assert "P1" in all_status
        assert "P2" in all_status
        assert all_status["P1"]["name"] == "P1"

    def test_get_stats(self) -> None:
        """get_stats() возвращает total, alive, dead, alive_percent."""
        process = Process(target=_dummy_target, name="TestProcess")
        status_obj = ProcessStatusMonitor([process])

        stats = status_obj.get_stats()

        assert stats["total"] == 1
        assert stats["alive"] == 0
        assert stats["dead"] == 1
        assert "alive_percent" in stats

    def test_get_alive_count(self) -> None:
        """get_alive_count() возвращает количество живых."""
        process = Process(target=_dummy_target, name="TestProcess")
        status_obj = ProcessStatusMonitor([process])

        assert status_obj.get_alive_count() == 0

        process.start()
        time.sleep(0.1)
        assert status_obj.get_alive_count() == 1

        process.terminate()
        process.join(timeout=1.0)


class TestStatusMonitorRegistryAliasB5:
    """B-5 (RS-2): ProcessStatusMonitor держит ЖИВУЮ ссылку на список реестра.

    remove_process должен снимать процесс так, чтобы монитор, захвативший
    os_processes в конструкторе (как PM: ProcessStatusMonitor(registry.os_processes)),
    видел снятие — иначе он перечисляет давно снесённые процессы (ghost).
    """

    def test_monitor_reflects_remove_process(self) -> None:
        from ..core.process_registry import ProcessRegistry

        registry = ProcessRegistry(logger=None)
        p1 = Process(target=_dummy_target, name="P1")
        p2 = Process(target=_dummy_target, name="P2")
        registry.add_process(p1)
        registry.add_process(p2)

        # Монитор захватывает ссылку на список реестра ОДИН раз (как в PM).
        monitor = ProcessStatusMonitor(registry.os_processes)
        assert monitor.get_total_count() == 2

        # Снятие через реестр (ребиндил бы список → стейл-алиас у монитора).
        registry.remove_process("P1")

        # Монитор ДОЛЖЕН увидеть снятие (живой алиас, slice-assign на месте).
        assert monitor.get_total_count() == 1
        assert monitor.get_process_status("P1") is None
        assert monitor.get_process_status("P2") is not None
