"""
Тесты для ProcessData и прокси-классов.
"""
import pickle
import pytest
from multiprocessing import Queue, Event

from multiprocess_framework.modules.Shared_resources_module import (
    ProcessData,
    ProcessConfiguration,
    QueuesProxy,
    EventsProxy
)


class TestQueuesProxy:
    """Тесты для QueuesProxy."""
    
    def test_get_queue_by_attribute(self):
        """Проверяет получение очереди через атрибут."""
        queue1 = Queue()
        queue2 = Queue()
        queues = {"data": queue1, "system": queue2}
        
        proxy = QueuesProxy(queues)
        
        assert proxy.data is queue1
        assert proxy.system is queue2
        assert proxy.nonexistent is None
    
    def test_get_queue_by_index(self):
        """Проверяет получение очереди через индекс."""
        queue1 = Queue()
        queues = {"data": queue1}
        
        proxy = QueuesProxy(queues)
        
        assert proxy["data"] is queue1
        assert proxy["nonexistent"] is None
    
    def test_contains(self):
        """Проверяет проверку наличия очереди."""
        queues = {"data": Queue()}
        proxy = QueuesProxy(queues)
        
        assert "data" in proxy
        assert "nonexistent" not in proxy
    
    def test_iteration(self):
        """Проверяет итерацию по именам очередей."""
        queues = {"data": Queue(), "system": Queue()}
        proxy = QueuesProxy(queues)
        
        names = list(proxy)
        assert len(names) == 2
        assert "data" in names
        assert "system" in names
    
    def test_len(self):
        """Проверяет получение количества очередей."""
        queues = {"data": Queue(), "system": Queue()}
        proxy = QueuesProxy(queues)
        
        assert len(proxy) == 2
    
    def test_keys_values_items(self):
        """Проверяет методы keys, values, items."""
        queue1 = Queue()
        queue2 = Queue()
        queues = {"data": queue1, "system": queue2}
        proxy = QueuesProxy(queues)
        
        assert set(proxy.keys()) == {"data", "system"}
        assert list(proxy.values()) == [queue1, queue2]
        assert len(list(proxy.items())) == 2


class TestEventsProxy:
    """Тесты для EventsProxy."""
    
    def test_get_event_by_attribute(self):
        """Проверяет получение события через атрибут."""
        event1 = Event()
        event2 = Event()
        events = {"start": event1, "stop": event2}
        
        proxy = EventsProxy(events)
        
        assert proxy.start is event1
        assert proxy.stop is event2
        assert proxy.nonexistent is None
    
    def test_get_event_by_index(self):
        """Проверяет получение события через индекс."""
        event1 = Event()
        events = {"start": event1}
        
        proxy = EventsProxy(events)
        
        assert proxy["start"] is event1
        assert proxy["nonexistent"] is None
    
    def test_contains(self):
        """Проверяет проверку наличия события."""
        events = {"start": Event()}
        proxy = EventsProxy(events)
        
        assert "start" in proxy
        assert "nonexistent" not in proxy
    
    def test_iteration(self):
        """Проверяет итерацию по именам событий."""
        events = {"start": Event(), "stop": Event()}
        proxy = EventsProxy(events)
        
        names = list(proxy)
        assert len(names) == 2
        assert "start" in names
        assert "stop" in names
    
    def test_len(self):
        """Проверяет получение количества событий."""
        events = {"start": Event(), "stop": Event()}
        proxy = EventsProxy(events)
        
        assert len(proxy) == 2


class TestProcessData:
    """Тесты для ProcessData."""
    
    def test_initialization(self):
        """Проверяет инициализацию ProcessData."""
        process_data = ProcessData(name="test_process")
        
        assert process_data.name == "test_process"
        assert process_data.status == "initializing"
        assert len(process_data.queues) == 0
        assert len(process_data.events) == 0
        assert isinstance(process_data.config, ProcessConfiguration)
    
    def test_queues_proxy_access(self):
        """Проверяет доступ к очередям через прокси."""
        queue1 = Queue()
        queue2 = Queue()
        
        process_data = ProcessData(
            name="test_process",
            _queues_dict={"data": queue1, "system": queue2}
        )
        
        # Доступ через прокси
        assert process_data.queues.data is queue1
        assert process_data.queues.system is queue2
        
        # Проверяем, что можем использовать очередь
        process_data.queues.data.put("test")
        assert process_data.queues.data.get() == "test"
    
    def test_events_proxy_access(self):
        """Проверяет доступ к событиям через прокси."""
        event1 = Event()
        event2 = Event()
        
        process_data = ProcessData(
            name="test_process",
            _events_dict={"start": event1, "stop": event2}
        )
        
        # Доступ через прокси
        assert process_data.events.start is event1
        assert process_data.events.stop is event2
        
        # Проверяем, что можем использовать событие
        process_data.events.start.set()
        assert process_data.events.start.is_set()
    
    def test_add_queue(self):
        """Проверяет добавление очереди."""
        process_data = ProcessData(name="test_process")
        queue = Queue()
        
        process_data.add_queue("data", queue)
        
        assert process_data.queues.data is queue
        assert process_data.get_queue("data") is queue
    
    def test_add_event(self):
        """Проверяет добавление события."""
        process_data = ProcessData(name="test_process")
        event = Event()
        
        process_data.add_event("start", event)
        
        assert process_data.events.start is event
        assert process_data.get_event("start") is event
    
    def test_update_status(self):
        """Проверяет обновление статуса."""
        process_data = ProcessData(name="test_process")
        
        process_data.update_status("running")
        
        assert process_data.status == "running"
    
    def test_update_metadata(self):
        """Проверяет обновление метаданных."""
        process_data = ProcessData(name="test_process")
        
        process_data.update_metadata(key1="value1", key2="value2")
        
        assert process_data.metadata["key1"] == "value1"
        assert process_data.metadata["key2"] == "value2"
    
    def test_update_custom(self):
        """Проверяет обновление кастомных данных."""
        process_data = ProcessData(name="test_process")
        
        process_data.update_custom(key1="value1")
        
        assert process_data.custom["key1"] == "value1"
    
    def test_to_dict(self):
        """Проверяет конвертацию в словарь."""
        queue = Queue()
        event = Event()
        
        process_data = ProcessData(
            name="test_process",
            _queues_dict={"data": queue},
            _events_dict={"start": event},
            status="running"
        )
        process_data.update_metadata(key="value")
        
        data_dict = process_data.to_dict()
        
        assert data_dict["name"] == "test_process"
        assert data_dict["status"] == "running"
        assert data_dict["queues_count"] == 1
        assert data_dict["events_count"] == 1
        assert "data" in data_dict["queue_types"]
        assert "start" in data_dict["event_names"]
        assert data_dict["metadata"]["key"] == "value"
    
    def test_convenient_access_example(self):
        """Проверяет удобный доступ к данным (пример использования)."""
        queue = Queue()
        event = Event()
        
        process_data = ProcessData(
            name="process_1",
            _queues_dict={"data": queue},
            _events_dict={"start": event}
        )
        
        # Удобный доступ к очередям
        process_data.queues.data.put("message")
        assert process_data.queues.data.get() == "message"
        
        # Удобный доступ к событиям
        process_data.events.start.set()
        assert process_data.events.start.is_set()
        
        # Доступ к конфигурации
        process_data.config.update_process_config(key="value")
        assert process_data.config.get_process_config("key") == "value"


class TestProcessDataSerialization:
    """Тесты сериализации ProcessData."""
    
    def test_basic_serialization(self):
        """Проверяет базовую сериализацию ProcessData."""
        process_data = ProcessData(name="test_process", status="running")
        
        try:
            serialized = pickle.dumps(process_data)
            deserialized = pickle.loads(serialized)
            
            assert deserialized.name == "test_process"
            assert deserialized.status == "running"
        except Exception as e:
            pytest.fail(f"Сериализация не удалась: {e}")
    
    def test_serialization_with_queues_and_events(self):
        """Проверяет сериализацию с очередями и событиями."""
        queue = Queue()
        event = Event()
        
        process_data = ProcessData(
            name="test_process",
            _queues_dict={"data": queue},
            _events_dict={"start": event}
        )
        
        try:
            serialized = pickle.dumps(process_data)
            deserialized = pickle.loads(serialized)
            
            # Queue и Event должны быть доступны после десериализации
            assert deserialized.queues.data is not None
            assert deserialized.events.start is not None
            
            # Проверяем использование
            deserialized.queues.data.put("test")
            assert deserialized.queues.data.get() == "test"
        except Exception as e:
            pytest.fail(f"Сериализация с очередями и событиями не удалась: {e}")
    
    def test_serialization_with_config(self):
        """Проверяет сериализацию с конфигурацией."""
        config = ProcessConfiguration()
        config.update_process_config(key="value")
        
        process_data = ProcessData(
            name="test_process",
            config=config
        )
        
        try:
            serialized = pickle.dumps(process_data)
            deserialized = pickle.loads(serialized)
            
            assert deserialized.config.get_process_config("key") == "value"
        except Exception as e:
            pytest.fail(f"Сериализация с конфигурацией не удалась: {e}")

