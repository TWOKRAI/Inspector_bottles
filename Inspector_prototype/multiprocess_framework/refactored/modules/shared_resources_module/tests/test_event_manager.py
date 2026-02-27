"""
Юнит-тесты для EventManager.
"""

import pytest
import time

from ..events.event_manager import EventManager, EventType


class TestEventManager:
    """Тесты для EventManager."""
    
    def test_initialization(self):
        """Тест инициализации менеджера событий."""
        manager = EventManager()
        assert manager is not None
        assert manager.manager_name == "EventManager"
    
    def test_initialize(self):
        """Тест инициализации."""
        manager = EventManager()
        assert manager.initialize() is True
        assert manager.is_initialized is True
    
    def test_emit_event(self):
        """Тест отправки события."""
        manager = EventManager()
        manager.initialize()
        
        result = manager.emit_event(
            EventType.PROCESS_STATE_CHANGED,
            process_name="test_process",
            status="running"
        )
        assert result is True
    
    def test_subscribe_unsubscribe(self):
        """Тест подписки и отписки от событий."""
        manager = EventManager()
        manager.initialize()
        
        callback_called = []
        
        def callback(event_data):
            callback_called.append(event_data)
        
        # Подписка
        assert manager.subscribe(EventType.PROCESS_STATE_CHANGED, callback) is True
        
        # Отправка события
        manager.emit_event(EventType.PROCESS_STATE_CHANGED, process_name="test")
        
        # Проверка вызова callback
        assert len(callback_called) == 1
        
        # Отписка
        assert manager.unsubscribe(EventType.PROCESS_STATE_CHANGED, callback) is True
        
        # Отправка еще одного события
        manager.emit_event(EventType.PROCESS_STATE_CHANGED, process_name="test2")
        
        # Callback не должен быть вызван снова
        assert len(callback_called) == 1
    
    def test_wait_for_event(self):
        """Тест ожидания события."""
        manager = EventManager()
        manager.initialize()
        
        # Отправляем событие в отдельном потоке
        import threading
        
        ready_event = threading.Event()  # Сигнал что wait_for_event начал ждать
        event_received = threading.Event()
        received_data = [None]
        error_occurred = [False]
        
        def send_event():
            # Ждем пока wait_for_event начнет ждать
            if not ready_event.wait(timeout=2.0):
                error_occurred[0] = True
                return
            time.sleep(0.1)  # Увеличиваем задержку для гарантии
            manager.emit_event(EventType.PROCESS_REGISTERED, process_name="test")
        
        def wait_for_event():
            ready_event.set()  # Сигнализируем что начали ждать
            time.sleep(0.05)  # Небольшая задержка чтобы убедиться что поток запустился
            data = manager.wait_for_event(EventType.PROCESS_REGISTERED, timeout=2.0)
            received_data[0] = data
            event_received.set()
        
        # Запускаем оба потока
        wait_thread = threading.Thread(target=wait_for_event, daemon=True)
        send_thread = threading.Thread(target=send_event, daemon=True)
        
        wait_thread.start()
        send_thread.start()
        
        # Ждем завершения
        wait_thread.join(timeout=3.0)
        send_thread.join(timeout=3.0)
        
        # Проверяем что не было ошибок
        assert not error_occurred[0], "Timeout waiting for ready_event"
        
        # Событие должно быть получено
        assert received_data[0] is not None, "Event was not received within timeout"
        assert received_data[0]["event_type"] == EventType.PROCESS_REGISTERED.value
        assert received_data[0]["process_name"] == "test"
    
    def test_get_stats(self):
        """Тест получения статистики."""
        manager = EventManager()
        manager.initialize()
        
        manager.emit_event(EventType.PROCESS_STATE_CHANGED)
        manager.subscribe(EventType.PROCESS_STATE_CHANGED, lambda x: None)
        
        stats = manager.get_stats()
        assert isinstance(stats, dict)
        assert 'events' in stats
        assert stats['events']['emitted'] >= 1

