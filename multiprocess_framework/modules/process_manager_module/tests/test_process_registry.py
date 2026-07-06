"""
Тесты для ProcessRegistry.

Проверяют реестр процессов: add, get, start_all, stop_all,
семантику «ensure stopped» stop_one/stop_many (Task 1.1
plans/2026-07-04_topology-switch-hardening.md).
"""

import signal
import time
from multiprocessing import Event, Process
from unittest.mock import MagicMock

from ..core.process_registry import ProcessRegistry


def _dummy_target() -> None:
    """Простая функция-цель для процесса."""
    time.sleep(2)


def _stubborn_target() -> None:
    """Игнорирует SIGTERM — умирает только от SIGKILL (эскалация terminate→kill)."""
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(30)


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

    def test_stop_many_stops_all_named_parallel(self) -> None:
        """stop_many(names) останавливает все указанные процессы, возвращает карту."""
        registry = ProcessRegistry(logger=None)
        registry._stop_events["A"] = Event()
        registry._stop_events["B"] = Event()
        pa = Process(target=time.sleep, args=(10,), name="A")
        pb = Process(target=time.sleep, args=(10,), name="B")
        registry.add_process(pa)
        registry.add_process(pb)
        pa.start()
        pb.start()
        time.sleep(0.05)

        # Общий дедлайн ~0.5с (sleep не слушает stop_event → terminate), параллельно
        result = registry.stop_many(["A", "B"], timeout=0.5)

        assert result == {"A": True, "B": True}
        assert registry._stop_events["A"].is_set()
        assert registry._stop_events["B"].is_set()
        assert not pa.is_alive()
        assert not pb.is_alive()

    def test_stop_many_unknown_process_is_already_stopped(self) -> None:
        """stop_many для несуществующего имени → True (ensure stopped, идемпотентно).

        «Призрак» (конфиг без Process-объекта) не должен валить stop-фазу
        switch рецепта — нечего останавливать = успех.
        """
        registry = ProcessRegistry(logger=None)
        result = registry.stop_many(["ghost"], timeout=0.5)
        assert result == {"ghost": True}

    def test_stop_one_unknown_process_is_already_stopped(self) -> None:
        """stop_one для несуществующего имени → True (паритет с PM.stop_process)."""
        registry = ProcessRegistry(logger=None)
        assert registry.stop_one("ghost", timeout=0.5) is True

    def test_stop_many_not_started_process_is_already_stopped(self) -> None:
        """Процесс зарегистрирован, но не стартован (pid=None) → True без эскалации."""
        registry = ProcessRegistry(logger=None)
        registry._stop_events["X"] = Event()
        p = Process(target=_dummy_target, name="X")
        registry.add_process(p)
        result = registry.stop_many(["X"], timeout=0.5)
        assert result == {"X": True}
        assert not registry._stop_events["X"].is_set()  # эскалация не понадобилась

    def test_stop_one_confirms_death_of_sigterm_ignoring_process(self) -> None:
        """Застрявший процесс (SIGTERM игнорирует) добивается kill и ПОДТВЕРЖДАЕТСЯ мёртвым."""
        registry = ProcessRegistry(logger=None)
        registry._stop_events["stuck"] = Event()
        p = Process(target=_stubborn_target, name="stuck")
        registry.add_process(p)
        p.start()
        time.sleep(0.3)  # дать ребёнку установить SIG_IGN

        assert registry.stop_one("stuck", timeout=0.3) is True
        assert not p.is_alive()

    def test_stop_many_mixed_ghost_and_stuck_and_graceful(self) -> None:
        """Смешанный набор: призрак + застрявший + спящий — все True, живых нет."""
        registry = ProcessRegistry(logger=None)
        registry._stop_events["stuck"] = Event()
        registry._stop_events["sleeper"] = Event()
        stuck = Process(target=_stubborn_target, name="stuck")
        sleeper = Process(target=_dummy_target, name="sleeper")
        registry.add_process(stuck)
        registry.add_process(sleeper)
        stuck.start()
        sleeper.start()
        time.sleep(0.3)

        result = registry.stop_many(["ghost", "stuck", "sleeper"], timeout=0.3)

        assert result == {"ghost": True, "stuck": True, "sleeper": True}
        assert not stuck.is_alive()
        assert not sleeper.is_alive()

    def test_stop_many_reports_false_for_unkillable_process(self) -> None:
        """Результат — по ФАКТУ смерти: is_alive()==True после kill → False."""
        registry = ProcessRegistry(logger=None)
        registry._stop_events["Z"] = Event()
        undead = MagicMock()
        undead.name = "Z"
        undead.is_alive.return_value = True  # переживает stop/terminate/kill
        registry.add_process(undead)

        result = registry.stop_many(["Z"], timeout=0.1)

        assert result == {"Z": False}
        undead.kill.assert_called_once()

    def test_remove_process_clears_stop_event(self) -> None:
        registry = ProcessRegistry(logger=None)
        registry._stop_events["X"] = Event()
        p = Process(target=time.sleep, args=(0.01,), name="X")
        registry.add_process(p)
        registry.remove_process("X")
        assert registry.get_process_by_name("X") is None
        assert "X" not in registry._stop_events
