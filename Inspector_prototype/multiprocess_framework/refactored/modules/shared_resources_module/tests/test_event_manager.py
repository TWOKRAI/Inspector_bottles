"""
Тесты для events/event_manager.py.
"""

import pickle
import pytest

from ..events.event_manager import EventManager
from ..types import EventType


@pytest.fixture
def em():
    manager = EventManager()
    manager.initialize()
    return manager


class TestEventManagerLifecycle:
    def test_initialize(self):
        em = EventManager()
        assert em.initialize() is True
        assert em.is_initialized is True

    def test_shutdown(self, em):
        assert em.shutdown() is True
        assert em.is_initialized is False
        assert em._event_queue is None

    def test_reinitialize(self):
        em = EventManager()
        em.reinitialize()
        assert em._event_queue is not None
        assert em._new_event_event is not None
        assert em._subscribers == {}


class TestEventManagerEmit:
    def test_emit_returns_true(self, em):
        assert em.emit_event(EventType.CONFIG_UPDATED) is True

    def test_emit_notifies_subscriber(self, em):
        received = []
        em.subscribe(EventType.PROCESS_REGISTERED, lambda data: received.append(data))
        em.emit_event(EventType.PROCESS_REGISTERED, process_name="p1")
        assert len(received) == 1
        assert received[0]["process_name"] == "p1"

    def test_emit_without_subscriber(self, em):
        assert em.emit_event(EventType.QUEUE_ADDED) is True

    def test_subscribe_and_unsubscribe(self, em):
        received = []
        cb = lambda data: received.append(data)
        em.subscribe(EventType.CONFIG_UPDATED, cb)
        em.emit_event(EventType.CONFIG_UPDATED)
        assert len(received) == 1
        em.unsubscribe(EventType.CONFIG_UPDATED, cb)
        em.emit_event(EventType.CONFIG_UPDATED)
        assert len(received) == 1  # не увеличилось


class TestEventManagerWait:
    def test_wait_for_event_returns_event(self, em):
        em.emit_event(EventType.PROCESS_REGISTERED, process_name="p1")
        event_data = em.wait_for_event(EventType.PROCESS_REGISTERED, timeout=0.5)
        assert event_data is not None
        assert event_data["event_type"] == "process_registered"

    def test_wait_timeout_returns_none(self, em):
        result = em.wait_for_event(EventType.PROCESS_REGISTERED, timeout=0.1)
        assert result is None


class TestEventManagerPickle:
    def test_pickle_excludes_queue(self, em):
        em2 = pickle.loads(pickle.dumps(em))
        assert em2._event_queue is None

    def test_pickle_excludes_subscribers(self, em):
        em.subscribe(EventType.CONFIG_UPDATED, lambda d: None)
        em2 = pickle.loads(pickle.dumps(em))
        assert em2._subscribers == {}

    def test_reinitialize_after_pickle(self, em):
        em2 = pickle.loads(pickle.dumps(em))
        assert em2.reinitialize() is True
        assert em2._event_queue is not None
        assert em2.emit_event(EventType.CONFIG_UPDATED) is True
