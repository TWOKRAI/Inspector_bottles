"""
Тесты для ProcessRegistry.

Проверяют реестр процессов: add, get, start_all, stop_all.
"""

import time
from multiprocessing import Event, Process

from ..core.process_registry import ProcessRegistry


def _dummy_target() -> None:
    """Простая функция-цель для процесса."""
    time.sleep(2)


class TestProcessRegistry:
    """Тесты ProcessRegistry."""

    def test_add_process(self) -> None:
        """add_process() добавляет процесс в os_processes."""
        registry = ProcessRegistry(logger=None)

        process = Process(target=_dummy_target, name="TestProcess")
        registry.add_process(process)

        assert len(registry.os_processes) == 1
        assert process in registry.os_processes

    def test_get_process_by_name(self) -> None:
        """get_process_by_name() возвращает процесс по имени."""
        registry = ProcessRegistry(logger=None)

        process = Process(target=_dummy_target, name="TestProcess")
        registry.add_process(process)

        found = registry.get_process_by_name("TestProcess")
        assert found is process

        not_found = registry.get_process_by_name("Unknown")
        assert not_found is None

    def test_start_all(self) -> None:
        """start_all() запускает все процессы."""
        registry = ProcessRegistry(logger=None)

        process = Process(target=_dummy_target, name="TestProcess")
        registry.add_process(process)

        registry.start_all()
        time.sleep(0.1)

        assert process.is_alive()

        process.terminate()
        process.join(timeout=1.0)

    def test_stop_all(self) -> None:
        """stop_all() останавливает все процессы."""
        registry = ProcessRegistry(logger=None)

        process = Process(target=_dummy_target, name="TestProcess")
        registry.add_process(process)
        registry._stop_events["TestProcess"] = Event()
        process.start()
        time.sleep(0.1)

        registry.stop_all(timeout=1.0)

        assert not process.is_alive()

        process.join(timeout=0.5)

    def test_stop_one_only_affects_named_process_events(self) -> None:
        """stop_one(name) не трогает stop_event другого процесса."""
        registry = ProcessRegistry(logger=None)
        ev_a = Event()
        ev_b = Event()
        registry._stop_events["A"] = ev_a
        registry._stop_events["B"] = ev_b
        pa = Process(target=time.sleep, args=(5,), name="A")
        pb = Process(target=time.sleep, args=(5,), name="B")
        registry.add_process(pa)
        registry.add_process(pb)
        pa.start()
        pb.start()
        time.sleep(0.05)
        registry.stop_one("A", timeout=2.0)
        assert ev_a.is_set()
        assert not ev_b.is_set()
        assert not pa.is_alive()
        assert pb.is_alive()
        pb.terminate()
        pb.join(timeout=1.0)

    def test_remove_process_clears_stop_event(self) -> None:
        registry = ProcessRegistry(logger=None)
        registry._stop_events["X"] = Event()
        p = Process(target=time.sleep, args=(0.01,), name="X")
        registry.add_process(p)
        registry.remove_process("X")
        assert registry.get_process_by_name("X") is None
        assert "X" not in registry._stop_events
