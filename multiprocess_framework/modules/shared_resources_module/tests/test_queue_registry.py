"""
Тесты для queues/core/manager.py.
"""

import time

import pytest
import multiprocessing

from ..queues import QueueRegistry
from ..state.process_state_registry import ProcessStateRegistry


@pytest.fixture
def psr():
    return ProcessStateRegistry()


@pytest.fixture
def qr(psr):
    registry = QueueRegistry(process_state_registry=psr)
    registry.initialize()
    return registry


class TestQueueRegistryCreate:
    def test_create_queues_from_config(self, qr):
        queues = qr.create_queues({"system": {"maxsize": 10}, "data": {}})
        assert "system" in queues
        assert "data" in queues
        assert isinstance(queues["system"], multiprocessing.queues.Queue)

    def test_create_queues_empty_config(self, qr):
        assert qr.create_queues({}) == {}
        assert qr.create_queues(None) == {}

    def test_create_and_register(self, qr, psr):
        psr.register_process("p1")
        queues = qr.create_and_register_queues("p1", {"system": {"maxsize": 5}})
        assert "system" in queues
        assert psr.get_queue("p1", "system") is queues["system"]

    def test_psr_is_source_of_truth(self, qr, psr):
        """После регистрации очередь должна быть в PSR."""
        psr.register_process("p1")
        qr.create_and_register_queues("p1", {"data": {}})
        assert psr.get_queue("p1", "data") is not None


class TestQueueRegistrySendReceive:
    def test_send_and_receive(self, qr, psr):
        psr.register_process("p1")
        qr.create_and_register_queues("p1", {"system": {}})
        assert qr.send_to_queue("p1", "system", "hello") is True
        msg = qr.receive_from_queue("p1", "system", timeout=0.5)
        assert msg == "hello"

    def test_receive_empty_returns_none(self, qr, psr):
        psr.register_process("p1")
        qr.create_and_register_queues("p1", {"system": {}})
        assert qr.receive_from_queue("p1", "system") is None

    def test_send_to_missing_queue_returns_false(self, qr):
        assert qr.send_to_queue("nonexistent", "system", "msg") is False


class TestQueueRegistryBroadcast:
    def test_broadcast_to_all(self, qr, psr):
        for name in ("p1", "p2", "p3"):
            psr.register_process(name)
            qr.create_and_register_queues(name, {"system": {}})
        count = qr.broadcast_message("broadcast_msg", queue_type="system")
        assert count == 3

    def test_broadcast_exclude(self, qr, psr):
        for name in ("p1", "p2"):
            psr.register_process(name)
            qr.create_and_register_queues(name, {"system": {}})
        count = qr.broadcast_message("msg", queue_type="system", exclude_process="p1")
        assert count == 1
        assert qr.receive_from_queue("p2", "system", timeout=0.5) == "msg"
        assert qr.receive_from_queue("p1", "system") is None


class TestQueueRegistrySystemGuard:
    """Ф3.3: предохранитель от вытеснения system-очереди."""

    def test_system_queue_not_evicted_on_full(self, qr, psr):
        """Полная system-очередь: старый элемент НЕ вытесняется, счётчик растёт."""
        psr.register_process("p1")
        qr.create_and_register_queues("p1", {"system": {"maxsize": 2}})
        # Заполняем system-очередь до предела (maxsize=2)
        assert qr.send_to_queue("p1", "system", "first") is True
        assert qr.send_to_queue("p1", "system", "second") is True
        # Очередь полна — попытка положить process.stop
        before = qr.get_stats()["queues"]["system_evict_blocked"]
        qr.send_to_queue("p1", "system", "process.stop")
        after = qr.get_stats()["queues"]["system_evict_blocked"]
        # Счётчик заблокированных вытеснений вырос
        assert after == before + 1
        # Старый элемент НЕ вытеснен — первым по-прежнему "first"
        assert qr.receive_from_queue("p1", "system", timeout=0.5) == "first"

    def test_data_queue_still_evicts_on_full(self, qr, psr):
        """Регресс: data-очередь по-прежнему вытесняет самый старый элемент."""
        psr.register_process("p1")
        qr.create_and_register_queues("p1", {"data": {"maxsize": 2}})
        assert qr.send_to_queue("p1", "data", "old") is True
        assert qr.send_to_queue("p1", "data", "mid") is True
        # macOS/spawn: multiprocessing.Queue флашит через фоновый feeder-поток
        # асинхронно — даём элементам осесть в pipe, иначе get_nowait при
        # вытеснении поймает Empty (это pre-existing поведение data-пути).
        time.sleep(0.1)
        # Очередь полна — вытеснение "old", место под "new"
        assert qr.send_to_queue("p1", "data", "new") is True
        # Счётчик system-блокировок не тронут (это data-путь)
        assert qr.get_stats()["queues"]["system_evict_blocked"] == 0
        # "old" вытеснен — первым идёт "mid"
        assert qr.receive_from_queue("p1", "data", timeout=0.5) == "mid"

    def test_get_stats_exposes_counter(self, qr):
        """get_stats отдаёт новый счётчик system_evict_blocked."""
        assert qr.get_stats()["queues"]["system_evict_blocked"] == 0


class TestQueueRegistryUtils:
    def test_get_queue_sizes(self, qr, psr):
        psr.register_process("p1")
        qr.create_and_register_queues("p1", {"system": {}})
        qr.send_to_queue("p1", "system", "item")
        sizes = qr.get_queue_sizes()
        assert "p1" in sizes

    def test_clear_queue(self, qr, psr):
        psr.register_process("p1")
        qr.create_and_register_queues("p1", {"system": {}})
        q = qr.get_queue("p1", "system")
        q.put("a")
        q.put("b")
        qr.clear_queue(q, keep_elements=0)
        assert qr.receive_from_queue("p1", "system") is None
