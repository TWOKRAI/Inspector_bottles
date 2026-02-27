"""
Юнит-тесты для SharedResourcesManager.
"""

import pytest
from multiprocessing import Queue, Event

from ..core.shared_resources_manager import SharedResourcesManager
from ...process_module.state.process_state_registry import ProcessStateRegistry
from ...process_module.state.process_data import ProcessData


class TestSharedResourcesManager:
    """Тесты для SharedResourcesManager."""
    
    def test_initialization(self):
        """Тест инициализации менеджера."""
        manager = SharedResourcesManager()
        assert manager is not None
        assert manager.manager_name == "SharedResourcesManager"
        assert manager.process_state_registry is not None
        assert manager.event_manager is not None
    
    def test_initialize(self):
        """Тест инициализации."""
        manager = SharedResourcesManager()
        assert manager.initialize() is True
        assert manager.is_initialized is True
    
    def test_shutdown(self):
        """Тест завершения работы."""
        manager = SharedResourcesManager()
        manager.initialize()
        assert manager.shutdown() is True
        assert manager.is_initialized is False
    
    def test_add_get_shared_resource(self):
        """Тест добавления и получения общих ресурсов."""
        manager = SharedResourcesManager()
        manager.add_shared_resource("test_resource", "test_value")
        assert manager.get_shared_resource("test_resource") == "test_value"
        assert manager.get_shared_resource("nonexistent") is None
    
    def test_register_process_state(self):
        """Тест регистрации состояния процесса."""
        manager = SharedResourcesManager()
        manager.initialize()
        
        result = manager.register_process_state(
            "test_process",
            initial_state={"status": "ready"}
        )
        assert result is True
        
        process_data = manager.get_process_data("test_process")
        assert process_data is not None
        assert process_data.name == "test_process"
    
    def test_get_process_data(self):
        """Тест получения ProcessData."""
        manager = SharedResourcesManager()
        manager.initialize()
        
        manager.register_process_state("test_process")
        process_data = manager.get_process_data("test_process")
        assert process_data is not None
        assert process_data.name == "test_process"
        
        assert manager.get_process_data("nonexistent") is None
    
    def test_get_all_process_data(self):
        """Тест получения всех ProcessData."""
        manager = SharedResourcesManager()
        manager.initialize()
        
        manager.register_process_state("process1")
        manager.register_process_state("process2")
        
        all_data = manager.get_all_process_data()
        assert len(all_data) == 2
        assert "process1" in all_data
        assert "process2" in all_data
    
    def test_get_process_queue(self):
        """Тест получения очереди процесса."""
        manager = SharedResourcesManager()
        manager.initialize()
        
        manager.register_process_state("test_process")
        process_data = manager.get_process_data("test_process")
        
        queue = Queue()
        process_data.add_queue("test_queue", queue)
        
        retrieved_queue = manager.get_process_queue("test_process", "test_queue")
        assert retrieved_queue is not None
        assert retrieved_queue == queue
    
    def test_get_process_event(self):
        """Тест получения события процесса."""
        manager = SharedResourcesManager()
        manager.initialize()
        
        manager.register_process_state("test_process")
        process_data = manager.get_process_data("test_process")
        
        event = Event()
        process_data.add_event("test_event", event)
        
        retrieved_event = manager.get_process_event("test_process", "test_event")
        assert retrieved_event is not None
        assert retrieved_event == event
    
    def test_get_stats(self):
        """Тест получения статистики."""
        manager = SharedResourcesManager()
        manager.initialize()
        
        manager.register_process_state("test_process")
        stats = manager.get_stats()
        
        assert isinstance(stats, dict)
        assert 'shared_resources' in stats
    
    def test_dynamic_access(self):
        """Тест динамического доступа к процессам."""
        manager = SharedResourcesManager()
        manager.initialize()
        
        manager.register_process_state("test_process")
        
        # Доступ через атрибут
        process_data = manager.test_process
        assert process_data is not None
        assert process_data.name == "test_process"
        
        # Ошибка для несуществующего процесса
        with pytest.raises(AttributeError):
            _ = manager.nonexistent_process

