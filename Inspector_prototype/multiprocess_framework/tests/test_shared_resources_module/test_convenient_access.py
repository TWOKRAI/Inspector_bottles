"""
Тесты для удобного интерфейса доступа к данным процессов.
"""
import pytest
from multiprocessing import Queue, Event

from multiprocess_framework.modules.Shared_resources_module import (
    SharedResourcesManager,
    ProcessConfiguration
)


class TestConvenientAccess:
    """Тесты для удобного интерфейса доступа."""
    
    def test_access_process_via_attribute(self):
        """Проверяет доступ к процессу через атрибут."""
        manager = SharedResourcesManager()
        manager.register_process_state("process_1")
        
        # Доступ через атрибут
        process_data = manager.process_1
        
        assert process_data is not None
        assert process_data.name == "process_1"
    
    def test_access_queues_via_attribute(self):
        """Проверяет доступ к очередям через атрибуты."""
        manager = SharedResourcesManager()
        manager.register_process_state("process_1")
        
        queue = Queue()
        manager.process_state_registry.add_queue("process_1", "data", queue)
        
        # Удобный доступ к очередям
        manager.process_1.queues.data.put("test_message")
        
        assert manager.process_1.queues.data.get() == "test_message"
    
    def test_access_events_via_attribute(self):
        """Проверяет доступ к событиям через атрибуты."""
        manager = SharedResourcesManager()
        manager.register_process_state("process_1")
        
        event = Event()
        manager.process_state_registry.add_event("process_1", "start", event)
        
        # Удобный доступ к событиям
        manager.process_1.events.start.set()
        
        assert manager.process_1.events.start.is_set()
    
    def test_access_config_via_attribute(self):
        """Проверяет доступ к конфигурации через атрибуты."""
        manager = SharedResourcesManager()
        
        config = ProcessConfiguration()
        config.update_process_config(key="value")
        
        manager.register_process_with_config("process_1", config)
        
        # Удобный доступ к конфигурации
        value = manager.process_1.config.get_process_config("key")
        
        assert value == "value"
    
    def test_full_example_usage(self):
        """Полный пример использования удобного интерфейса."""
        manager = SharedResourcesManager()
        
        # Регистрируем процесс с конфигурацией
        config = ProcessConfiguration()
        config.update_process_config(database_host="localhost")
        manager.register_process_with_config("process_1", config)
        
        # Добавляем очереди и события
        data_queue = Queue()
        system_queue = Queue()
        start_event = Event()
        
        manager.process_state_registry.add_queue("process_1", "data", data_queue)
        manager.process_state_registry.add_queue("process_1", "system", system_queue)
        manager.process_state_registry.add_event("process_1", "start", start_event)
        
        # Используем удобный интерфейс
        # Доступ к очередям
        manager.process_1.queues.data.put({"type": "message", "content": "hello"})
        manager.process_1.queues.system.put("system_message")
        
        # Доступ к событиям
        manager.process_1.events.start.set()
        
        # Доступ к конфигурации
        db_host = manager.process_1.config.get_process_config("database_host")
        
        # Проверяем результаты
        assert manager.process_1.queues.data.get() == {"type": "message", "content": "hello"}
        assert manager.process_1.queues.system.get() == "system_message"
        assert manager.process_1.events.start.is_set()
        assert db_host == "localhost"
    
    def test_access_multiple_processes(self):
        """Проверяет доступ к нескольким процессам."""
        manager = SharedResourcesManager()
        
        manager.register_process_state("process_1")
        manager.register_process_state("process_2")
        
        queue1 = Queue()
        queue2 = Queue()
        
        manager.process_state_registry.add_queue("process_1", "data", queue1)
        manager.process_state_registry.add_queue("process_2", "data", queue2)
        
        # Отправляем сообщения в разные процессы
        manager.process_1.queues.data.put("message1")
        manager.process_2.queues.data.put("message2")
        
        assert manager.process_1.queues.data.get() == "message1"
        assert manager.process_2.queues.data.get() == "message2"
    
    def test_access_nonexistent_process(self):
        """Проверяет обработку доступа к несуществующему процессу."""
        manager = SharedResourcesManager()
        
        with pytest.raises(AttributeError) as exc_info:
            _ = manager.nonexistent_process
        
        assert "nonexistent_process" in str(exc_info.value)
    
    def test_access_nonexistent_queue(self):
        """Проверяет доступ к несуществующей очереди."""
        manager = SharedResourcesManager()
        manager.register_process_state("process_1")
        
        # Доступ к несуществующей очереди возвращает None
        assert manager.process_1.queues.nonexistent is None
    
    def test_access_nonexistent_event(self):
        """Проверяет доступ к несуществующему событию."""
        manager = SharedResourcesManager()
        manager.register_process_state("process_1")
        
        # Доступ к несуществующему событию возвращает None
        assert manager.process_1.events.nonexistent is None
    
    def test_queues_proxy_iteration(self):
        """Проверяет итерацию по очередям через прокси."""
        manager = SharedResourcesManager()
        manager.register_process_state("process_1")
        
        manager.process_state_registry.add_queue("process_1", "data", Queue())
        manager.process_state_registry.add_queue("process_1", "system", Queue())
        
        # Итерация по именам очередей
        queue_names = list(manager.process_1.queues)
        
        assert len(queue_names) == 2
        assert "data" in queue_names
        assert "system" in queue_names
    
    def test_events_proxy_iteration(self):
        """Проверяет итерацию по событиям через прокси."""
        manager = SharedResourcesManager()
        manager.register_process_state("process_1")
        
        manager.process_state_registry.add_event("process_1", "start", Event())
        manager.process_state_registry.add_event("process_1", "stop", Event())
        
        # Итерация по именам событий
        event_names = list(manager.process_1.events)
        
        assert len(event_names) == 2
        assert "start" in event_names
        assert "stop" in event_names

