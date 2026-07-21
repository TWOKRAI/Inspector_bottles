"""
Тесты для events/core/manager.py.
"""

import pickle
import pytest

from ..events import EventManager
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


class TestEmitEventOrphanChannelGuard:
    """LIVE-1: канал system_events осиротел (потребителя нет). emit_event шлёт в роутер
    ТОЛЬКО когда канал зарегистрирован; без него cross-process рассылка отключена (иначе
    очередь PM набивалась → errors росли), но локальная семантика (подписчики + _event_queue)
    сохраняется. Фикс LIVE-1 = перестать регистрировать канал → этот гейт сам разоружает send."""

    def test_no_router_send_without_channel(self):
        from unittest.mock import Mock

        router = Mock()
        router.get_channel = Mock(return_value=None)  # канал НЕ зарегистрирован
        router.send = Mock()
        em = EventManager(router_manager=router)
        em.initialize()
        received: list = []
        em.subscribe(EventType.PROCESS_REGISTERED, lambda d: received.append(d))

        assert em.emit_event(EventType.PROCESS_REGISTERED, process_name="p1") is True
        router.send.assert_not_called()  # осиротевшая рассылка отключена
        assert len(received) == 1  # локальные подписчики целы
        # локальная очередь цела (mp.Queue async → ждём через wait_for_event, не get_nowait).
        evt = em.wait_for_event(EventType.PROCESS_REGISTERED, timeout=1.0)
        assert evt is not None and evt["process_name"] == "p1"
        assert em._stats["errors"] == 0  # never-drop путь не задействован → errors не растут

    def test_router_send_when_channel_present(self):
        """Контраст: канал есть → рассылка идёт (гейт — именно регистрация канала)."""
        from unittest.mock import Mock

        router = Mock()
        router.get_channel = Mock(return_value=object())  # канал зарегистрирован
        router.send = Mock(return_value={"status": "success"})
        em = EventManager(router_manager=router)
        em.initialize()
        em.emit_event(EventType.PROCESS_REGISTERED, process_name="p1")
        router.send.assert_called_once()


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

        def cb(data):
            received.append(data)

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
