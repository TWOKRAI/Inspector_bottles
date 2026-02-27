"""
Тесты для ProcessStateRegistry.
"""
import pytest
from multiprocessing import Queue, Event

from multiprocess_framework.modules.Shared_resources_module import (
    ProcessStateRegistry,
    ProcessData,
    ProcessConfiguration
)


class TestProcessStateRegistry:
    """Тесты для ProcessStateRegistry."""
    
    def test_initialization(self):
        """Проверяет инициализацию ProcessStateRegistry."""
        registry = ProcessStateRegistry()
        
        assert len(registry.states) == 0
    
    def test_register_process(self):
        """Проверяет регистрацию процесса."""
        registry = ProcessStateRegistry()
        
        result = registry.register_process("test_process")
        assert result is True
        
        process_data = registry.get_process_data("test_process")
        assert process_data is not None
        assert process_data.name == "test_process"
        assert process_data.status == ProcessStateRegistry.STATUS_INITIALIZING
    
    def test_register_process_with_initial_state(self):
        """Проверяет регистрацию процесса с начальным состоянием."""
        registry = ProcessStateRegistry()
        
        initial_state = {
            "status": "running",
            "metadata": {"key": "value"}
        }
        
        result = registry.register_process("test_process", initial_state=initial_state)
        assert result is True
        
        process_data = registry.get_process_data("test_process")
        assert process_data.status == "running"
        assert process_data.metadata["key"] == "value"
    
    def test_register_process_with_config(self):
        """Проверяет регистрацию процесса с конфигурацией."""
        registry = ProcessStateRegistry()
        
        config = ProcessConfiguration()
        config.update_process_config(key="value")
        
        result = registry.register_process_with_config("test_process", config)
        assert result is True
        
        process_data = registry.get_process_data("test_process")
        assert process_data.config.get_process_config("key") == "value"
    
    def test_add_queue(self):
        """Проверяет добавление очереди."""
        registry = ProcessStateRegistry()
        registry.register_process("test_process")
        
        queue = Queue()
        result = registry.add_queue("test_process", "data", queue)
        
        assert result is True
        assert registry.get_queue("test_process", "data") is queue
    
    def test_add_event(self):
        """Проверяет добавление события."""
        registry = ProcessStateRegistry()
        registry.register_process("test_process")
        
        event = Event()
        result = registry.add_event("test_process", "start", event)
        
        assert result is True
        assert registry.get_event("test_process", "start") is event
    
    def test_update_state(self):
        """Проверяет обновление состояния процесса."""
        registry = ProcessStateRegistry()
        registry.register_process("test_process")
        
        result = registry.update_state(
            "test_process",
            status="running",
            metadata={"key": "value"}
        )
        
        assert result is True
        process_data = registry.get_process_data("test_process")
        assert process_data.status == "running"
        assert process_data.metadata["key"] == "value"
    
    def test_get_state(self):
        """Проверяет получение состояния процесса."""
        registry = ProcessStateRegistry()
        registry.register_process("test_process")
        
        state = registry.get_state("test_process")
        
        assert state is not None
        assert state["name"] == "test_process"
        assert state["status"] == ProcessStateRegistry.STATUS_INITIALIZING
    
    def test_get_all_states(self):
        """Проверяет получение всех состояний."""
        registry = ProcessStateRegistry()
        registry.register_process("process1")
        registry.register_process("process2")
        
        all_states = registry.get_all_states()
        
        assert len(all_states) == 2
        assert "process1" in all_states
        assert "process2" in all_states
    
    def test_get_process_names(self):
        """Проверяет получение списка имен процессов."""
        registry = ProcessStateRegistry()
        registry.register_process("process1")
        registry.register_process("process2")
        
        names = registry.get_process_names()
        
        assert len(names) == 2
        assert "process1" in names
        assert "process2" in names
    
    def test_unregister_process(self):
        """Проверяет удаление процесса из реестра."""
        registry = ProcessStateRegistry()
        registry.register_process("test_process")
        
        result = registry.unregister_process("test_process")
        
        assert result is True
        assert registry.get_process_data("test_process") is None
    
    def test_has_process(self):
        """Проверяет проверку наличия процесса."""
        registry = ProcessStateRegistry()
        registry.register_process("test_process")
        
        assert registry.has_process("test_process") is True
        assert registry.has_process("nonexistent") is False
    
    def test_get_stats(self):
        """Проверяет получение статистики."""
        registry = ProcessStateRegistry()
        registry.register_process("process1")
        registry.register_process("process2")
        
        stats = registry.get_stats()
        
        assert stats["total_processes"] == 2
        assert "process1" in stats["processes"]
        assert "process2" in stats["processes"]
    
    def test_auto_register_on_add_queue(self):
        """Проверяет автоматическую регистрацию при добавлении очереди."""
        registry = ProcessStateRegistry()
        
        queue = Queue()
        registry.add_queue("new_process", "data", queue)
        
        assert registry.has_process("new_process")
        assert registry.get_queue("new_process", "data") is queue
    
    def test_auto_register_on_add_event(self):
        """Проверяет автоматическую регистрацию при добавлении события."""
        registry = ProcessStateRegistry()
        
        event = Event()
        registry.add_event("new_process", "start", event)
        
        assert registry.has_process("new_process")
        assert registry.get_event("new_process", "start") is event

