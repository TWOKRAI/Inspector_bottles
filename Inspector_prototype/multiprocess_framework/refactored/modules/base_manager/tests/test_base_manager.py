"""
Тесты для BaseManager.
"""

import pytest
from ..core.base_manager import BaseManager


class MockManager(BaseManager):
    """Тестовый менеджер для проверки BaseManager."""
    
    def initialize(self) -> bool:
        self.is_initialized = True
        return True
    
    def shutdown(self) -> bool:
        self.is_initialized = False
        return True


class MockAdapter:
    """Тестовый адаптер."""
    
    def __init__(self, manager, process=None):
        self.manager = manager
        self.process = process
        self.adapter_name = "test_adapter"
        self._initialized = False
    
    def setup(self) -> bool:
        self._initialized = True
        return True
    
    def is_initialized(self) -> bool:
        return self._initialized


class TestBaseManager:
    """Тесты для BaseManager."""
    
    def test_create_manager(self):
        """Тест создания менеджера."""
        manager = MockManager("test_manager")
        
        assert manager.manager_name == "test_manager"
        assert manager.is_initialized is False
        assert manager.process is None
    
    def test_initialize(self):
        """Тест инициализации менеджера."""
        manager = MockManager("test_manager")
        
        result = manager.initialize()
        
        assert result is True
        assert manager.is_initialized is True
    
    def test_shutdown(self):
        """Тест завершения менеджера."""
        manager = MockManager("test_manager")
        manager.initialize()
        
        result = manager.shutdown()
        
        assert result is True
        assert manager.is_initialized is False
    
    def test_attach_adapter(self):
        """Тест подключения адаптера."""
        manager = MockManager("test_manager")
        adapter = MockAdapter(manager)
        
        result = manager.attach_adapter(adapter, name="test")
        
        assert result is True
        assert manager.has_adapter("test")
        assert manager.get_adapter("test") == adapter
    
    def test_get_adapter_by_name(self):
        """Тест получения адаптера по имени."""
        manager = MockManager("test_manager")
        adapter = MockAdapter(manager)
        
        manager.attach_adapter(adapter, name="test")
        
        assert manager.get_adapter("test") == adapter
    
    def test_list_adapters(self):
        """Тест получения списка адаптеров."""
        manager = MockManager("test_manager")
        adapter1 = MockAdapter(manager)
        adapter2 = MockAdapter(manager)
        
        manager.attach_adapter(adapter1, name="adapter1")
        manager.attach_adapter(adapter2, name="adapter2")
        
        adapters = manager.list_adapters()
        
        assert "adapter1" in adapters
        assert "adapter2" in adapters
    
    def test_detach_adapter(self):
        """Тест отключения адаптера."""
        manager = MockManager("test_manager")
        adapter = MockAdapter(manager)
        
        manager.attach_adapter(adapter, name="test")
        result = manager.detach_adapter("test")
        
        assert result is True
        assert not manager.has_adapter("test")
    
    def test_get_stats(self):
        """Тест получения статистики."""
        manager = MockManager("test_manager")
        adapter = MockAdapter(manager)
        
        manager.attach_adapter(adapter, name="test")
        stats = manager.get_stats()
        
        assert stats["manager_name"] == "test_manager"
        assert stats["is_initialized"] is False
        assert "test" in stats["adapters"]
    
    def test_events(self):
        """Тест событий."""
        manager = MockManager("test_manager")
        event_called = []
        
        def handler(data):
            event_called.append(data)
        
        manager.on_event("test_event", handler)
        manager.emit_event("test_event", {"data": "test"})
        
        assert len(event_called) == 1
        assert event_called[0]["data"] == "test"
    
    def test_magic_access_adapter(self):
        """Тест magic-доступа к адаптеру."""
        manager = MockManager("test_manager")
        adapter = MockAdapter(manager)
        
        manager.attach_adapter(adapter, name="test")
        
        # Доступ через magic-атрибут
        assert manager.test == adapter

