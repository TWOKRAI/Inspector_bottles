"""
Тесты для SharedResourcesManager.
"""
import pickle
import pytest
from multiprocessing import Queue, Event

from multiprocess_framework.modules.Shared_resources_module import (
    SharedResourcesManager,
    ProcessData,
    ProcessConfiguration
)


class TestSharedResourcesManager:
    """Тесты для SharedResourcesManager."""
    
    def test_initialization(self):
        """Проверяет инициализацию SharedResourcesManager."""
        manager = SharedResourcesManager()
        
        assert manager.process_state_registry is not None
        assert isinstance(manager.shared_resources, dict)
        assert len(manager.shared_resources) == 0
    
    def test_add_get_shared_resource(self):
        """Проверяет добавление и получение общих ресурсов."""
        manager = SharedResourcesManager()
        
        test_resource = {"key": "value"}
        manager.add_shared_resource("test_resource", test_resource)
        
        assert manager.get_shared_resource("test_resource") == test_resource
        assert manager.get_shared_resource("nonexistent") is None
    
    def test_register_process(self):
        """Проверяет регистрацию процесса."""
        manager = SharedResourcesManager()
        
        result = manager.register_process_state("test_process")
        assert result is True
        
        process_data = manager.get_process_data("test_process")
        assert process_data is not None
        assert process_data.name == "test_process"
    
    def test_register_process_with_config(self):
        """Проверяет регистрацию процесса с конфигурацией."""
        manager = SharedResourcesManager()
        
        config = ProcessConfiguration()
        config.update_process_config(key="value")
        
        result = manager.register_process_with_config("test_process", config)
        assert result is True
        
        process_data = manager.get_process_data("test_process")
        assert process_data.config.get_process_config("key") == "value"
    
    def test_get_process_queue(self):
        """Проверяет получение очереди процесса."""
        manager = SharedResourcesManager()
        manager.register_process_state("test_process")
        
        queue = Queue()
        manager.process_state_registry.add_queue("test_process", "data", queue)
        
        retrieved_queue = manager.get_process_queue("test_process", "data")
        assert retrieved_queue is queue
    
    def test_get_process_event(self):
        """Проверяет получение события процесса."""
        manager = SharedResourcesManager()
        manager.register_process_state("test_process")
        
        event = Event()
        manager.process_state_registry.add_event("test_process", "start", event)
        
        retrieved_event = manager.get_process_event("test_process", "start")
        assert retrieved_event is event
    
    def test_get_all_process_data(self):
        """Проверяет получение всех данных процессов."""
        manager = SharedResourcesManager()
        
        manager.register_process_state("process1")
        manager.register_process_state("process2")
        
        all_data = manager.get_all_process_data()
        assert len(all_data) == 2
        assert "process1" in all_data
        assert "process2" in all_data
    
    def test_dynamic_access_to_process(self):
        """Проверяет динамический доступ к процессам через атрибуты."""
        manager = SharedResourcesManager()
        manager.register_process_state("process_1")
        
        # Доступ через атрибут
        process_data = manager.process_1
        assert process_data is not None
        assert process_data.name == "process_1"
    
    def test_dynamic_access_nonexistent_process(self):
        """Проверяет обработку доступа к несуществующему процессу."""
        manager = SharedResourcesManager()
        
        with pytest.raises(AttributeError) as exc_info:
            _ = manager.nonexistent_process
        
        assert "nonexistent_process" in str(exc_info.value)
        assert "Available processes" in str(exc_info.value)
    
    def test_get_stats(self):
        """Проверяет получение статистики."""
        manager = SharedResourcesManager()
        manager.register_process_state("process1")
        manager.add_shared_resource("test", "value")
        
        stats = manager.get_stats()
        assert "process_state_registry" in stats
        assert "shared_resources" in stats
        assert stats["shared_resources"]["count"] == 1
    
    def test_str_representation(self):
        """Проверяет строковое представление."""
        manager = SharedResourcesManager()
        manager.register_process_state("process1")
        
        str_repr = str(manager)
        assert "SharedResourcesManager" in str_repr
        assert "processes=" in str_repr


class TestSharedResourcesManagerSerialization:
    """Тесты сериализации SharedResourcesManager."""
    
    def test_basic_serialization(self):
        """Проверяет базовую сериализацию SharedResourcesManager."""
        manager = SharedResourcesManager()
        manager.register_process_state("test_process")
        
        try:
            serialized = pickle.dumps(manager)
            deserialized = pickle.loads(serialized)
            
            assert deserialized.process_state_registry is not None
            process_data = deserialized.get_process_data("test_process")
            assert process_data is not None
        except Exception as e:
            pytest.fail(f"Сериализация не удалась: {e}")
    
    def test_serialization_with_queues_and_events(self):
        """Проверяет сериализацию с очередями и событиями."""
        manager = SharedResourcesManager()
        manager.register_process_state("test_process")
        
        queue = Queue()
        event = Event()
        
        manager.process_state_registry.add_queue("test_process", "data", queue)
        manager.process_state_registry.add_event("test_process", "start", event)
        
        try:
            serialized = pickle.dumps(manager)
            deserialized = pickle.loads(serialized)
            
            # Queue и Event должны быть доступны после десериализации
            retrieved_queue = deserialized.get_process_queue("test_process", "data")
            retrieved_event = deserialized.get_process_event("test_process", "start")
            
            assert retrieved_queue is not None
            assert retrieved_event is not None
            
            # Проверяем, что можем использовать очередь
            retrieved_queue.put("test")
            assert retrieved_queue.get() == "test"
        except Exception as e:
            pytest.fail(f"Сериализация с очередями и событиями не удалась: {e}")
    
    def test_serialization_with_config(self):
        """Проверяет сериализацию с конфигурацией."""
        manager = SharedResourcesManager()
        
        config = ProcessConfiguration()
        config.update_process_config(key="value")
        
        manager.register_process_with_config("test_process", config)
        
        try:
            serialized = pickle.dumps(manager)
            deserialized = pickle.loads(serialized)
            
            process_data = deserialized.get_process_data("test_process")
            assert process_data.config.get_process_config("key") == "value"
        except Exception as e:
            pytest.fail(f"Сериализация с конфигурацией не удалась: {e}")

