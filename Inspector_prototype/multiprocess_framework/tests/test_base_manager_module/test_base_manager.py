"""
Комплексные тесты для BaseManager.

Проверяет все аспекты работы базового класса менеджеров.
"""
import pytest
from unittest.mock import Mock

from multiprocess_framework.modules.Base_manager_module.base_manager import BaseManager


class ConcreteManager(BaseManager):
    """Конкретная реализация BaseManager для тестирования."""
    
    def __init__(self, manager_name: str, process=None, init_result=True, shutdown_result=True):
        super().__init__(manager_name, process)
        self._init_result = init_result
        self._shutdown_result = shutdown_result
        self._init_called = False
        self._shutdown_called = False
    
    def initialize(self) -> bool:
        """Реализация абстрактного метода initialize."""
        self._init_called = True
        self.is_initialized = self._init_result
        return self._init_result
    
    def shutdown(self) -> bool:
        """Реализация абстрактного метода shutdown."""
        self._shutdown_called = True
        self.is_initialized = False
        return self._shutdown_result


@pytest.fixture
def process_mock():
    """Фикстура для мока процесса."""
    process = Mock()
    process.name = "TestProcess"
    return process


class TestBaseManager:
    """Тесты для BaseManager."""
    
    def test_initialization_with_name_only(self):
        """Тест инициализации только с именем."""
        manager = ConcreteManager("TestManager")
        
        assert manager.manager_name == "TestManager"
        assert manager.process is None
        assert manager.is_initialized is False
        assert manager._event_handlers == {}
    
    def test_initialization_with_process(self, process_mock):
        """Тест инициализации с процессом."""
        manager = ConcreteManager("TestManager", process=process_mock)
        
        assert manager.manager_name == "TestManager"
        assert manager.process == process_mock
        assert manager.is_initialized is False
    
    def test_base_manager_is_abstract(self):
        """Тест что BaseManager является абстрактным классом."""
        with pytest.raises(TypeError):
            BaseManager("test")
    
    def test_initialize_method(self):
        """Тест метода initialize."""
        manager = ConcreteManager("TestManager", init_result=True)
        
        assert manager.is_initialized is False
        result = manager.initialize()
        
        assert result is True
        assert manager.is_initialized is True
        assert manager._init_called is True
    
    def test_initialize_method_failure(self):
        """Тест метода initialize при неудаче."""
        manager = ConcreteManager("TestManager", init_result=False)
        
        result = manager.initialize()
        
        assert result is False
        assert manager.is_initialized is False
    
    def test_shutdown_method(self):
        """Тест метода shutdown."""
        manager = ConcreteManager("TestManager", shutdown_result=True)
        manager.is_initialized = True
        
        result = manager.shutdown()
        
        assert result is True
        assert manager.is_initialized is False
        assert manager._shutdown_called is True
    
    def test_shutdown_method_failure(self):
        """Тест метода shutdown при неудаче."""
        manager = ConcreteManager("TestManager", shutdown_result=False)
        manager.is_initialized = True
        
        result = manager.shutdown()
        
        assert result is False
        assert manager.is_initialized is False
    
    def test_get_stats_without_process(self):
        """Тест получения статистики без процесса."""
        manager = ConcreteManager("TestManager")
        manager.is_initialized = True
        
        stats = manager.get_stats()
        
        assert stats["manager_name"] == "TestManager"
        assert stats["is_initialized"] is True
        assert stats["process_name"] == "standalone"
    
    def test_get_stats_with_process(self, process_mock):
        """Тест получения статистики с процессом."""
        manager = ConcreteManager("TestManager", process=process_mock)
        manager.is_initialized = True
        
        stats = manager.get_stats()
        
        assert stats["manager_name"] == "TestManager"
        assert stats["is_initialized"] is True
        assert stats["process_name"] == "TestProcess"
    
    def test_get_stats_with_process_without_name(self):
        """Тест получения статистики с процессом без атрибута name."""
        # Используем обычный объект без атрибутов
        process_no_name = object()
        manager = ConcreteManager("TestManager", process=process_no_name)
        
        stats = manager.get_stats()
        
        assert stats["process_name"] == "unknown"
    
    def test_on_event_single_handler(self):
        """Тест регистрации одного обработчика события."""
        manager = ConcreteManager("TestManager")
        handler = Mock()
        
        manager.on_event("test_event", handler)
        
        assert "test_event" in manager._event_handlers
        assert len(manager._event_handlers["test_event"]) == 1
        assert handler in manager._event_handlers["test_event"]
    
    def test_on_event_multiple_handlers(self):
        """Тест регистрации нескольких обработчиков события."""
        manager = ConcreteManager("TestManager")
        handler1 = Mock()
        handler2 = Mock()
        handler3 = Mock()
        
        manager.on_event("test_event", handler1)
        manager.on_event("test_event", handler2)
        manager.on_event("test_event", handler3)
        
        assert len(manager._event_handlers["test_event"]) == 3
        assert handler1 in manager._event_handlers["test_event"]
        assert handler2 in manager._event_handlers["test_event"]
        assert handler3 in manager._event_handlers["test_event"]
    
    def test_on_event_different_event_types(self):
        """Тест регистрации обработчиков для разных типов событий."""
        manager = ConcreteManager("TestManager")
        handler1 = Mock()
        handler2 = Mock()
        
        manager.on_event("event1", handler1)
        manager.on_event("event2", handler2)
        
        assert "event1" in manager._event_handlers
        assert "event2" in manager._event_handlers
        assert len(manager._event_handlers["event1"]) == 1
        assert len(manager._event_handlers["event2"]) == 1
    
    def test_emit_event_with_handler(self):
        """Тест генерации события с зарегистрированным обработчиком."""
        manager = ConcreteManager("TestManager")
        handler = Mock()
        manager.on_event("test_event", handler)
        
        event_data = {"key": "value", "number": 42}
        manager.emit_event("test_event", event_data)
        
        handler.assert_called_once_with(event_data)
    
    def test_emit_event_multiple_handlers(self):
        """Тест генерации события с несколькими обработчиками."""
        manager = ConcreteManager("TestManager")
        handler1 = Mock()
        handler2 = Mock()
        handler3 = Mock()
        
        manager.on_event("test_event", handler1)
        manager.on_event("test_event", handler2)
        manager.on_event("test_event", handler3)
        
        event_data = {"key": "value"}
        manager.emit_event("test_event", event_data)
        
        handler1.assert_called_once_with(event_data)
        handler2.assert_called_once_with(event_data)
        handler3.assert_called_once_with(event_data)
    
    def test_emit_event_without_handlers(self):
        """Тест генерации события без обработчиков."""
        manager = ConcreteManager("TestManager")
        manager.emit_event("nonexistent_event", {"data": "test"})
    
    def test_emit_event_handler_exception(self):
        """Тест обработки исключений в обработчиках событий."""
        manager = ConcreteManager("TestManager")
        
        def failing_handler(data):
            raise ValueError("Test error")
        
        working_handler = Mock()
        
        manager.on_event("test_event", failing_handler)
        manager.on_event("test_event", working_handler)
        
        event_data = {"key": "value"}
        manager.emit_event("test_event", event_data)
        
        assert working_handler.called is True
    
    def test_str_representation(self):
        """Тест строкового представления менеджера."""
        manager = ConcreteManager("TestManager")
        
        str_repr = str(manager)
        
        assert "TestManager" in str_repr
        assert "initialized" in str_repr.lower()
        assert "False" in str_repr
    
    def test_str_representation_initialized(self):
        """Тест строкового представления инициализированного менеджера."""
        manager = ConcreteManager("TestManager")
        manager.is_initialized = True
        
        str_repr = str(manager)
        
        assert "TestManager" in str_repr
        assert "True" in str_repr
    
    def test_lifecycle_sequence(self):
        """Тест полного жизненного цикла менеджера."""
        manager = ConcreteManager("TestManager")
        
        assert manager.is_initialized is False
        
        result = manager.initialize()
        assert result is True
        assert manager.is_initialized is True
        
        result = manager.shutdown()
        assert result is True
        assert manager.is_initialized is False
    
    def test_event_system_integration(self):
        """Тест интеграции системы событий."""
        manager = ConcreteManager("TestManager")
        
        init_handler = Mock()
        shutdown_handler = Mock()
        
        manager.on_event("initialized", init_handler)
        manager.on_event("shutdown", shutdown_handler)
        
        manager.emit_event("initialized", {"manager": "TestManager"})
        manager.emit_event("shutdown", {"manager": "TestManager"})
        
        init_handler.assert_called_once()
        shutdown_handler.assert_called_once()


class TestBaseManagerIntegration:
    """Интеграционные тесты для BaseManager."""
    
    def test_manager_with_process_and_events(self, process_mock):
        """Тест менеджера с процессом и системой событий."""
        manager = ConcreteManager("IntegrationManager", process=process_mock)
        
        assert manager.process == process_mock
        
        stats = manager.get_stats()
        assert stats["process_name"] == "TestProcess"
        
        event_handler = Mock()
        manager.on_event("test", event_handler)
        manager.emit_event("test", {"data": "test"})
        event_handler.assert_called_once()
    
    def test_multiple_managers_independence(self):
        """Тест независимости нескольких менеджеров."""
        manager1 = ConcreteManager("Manager1")
        manager2 = ConcreteManager("Manager2")
        
        handler1 = Mock()
        handler2 = Mock()
        
        manager1.on_event("event", handler1)
        manager2.on_event("event", handler2)
        
        manager1.emit_event("event", {"manager": "1"})
        manager2.emit_event("event", {"manager": "2"})
        
        handler1.assert_called_once_with({"manager": "1"})
        handler2.assert_called_once_with({"manager": "2"})
        
        assert handler1.call_count == 1
        assert handler2.call_count == 1
    
    # ========== Тесты для методов управления адаптерами ==========
    
    def test_attach_adapter_with_name(self):
        """Тест подключения адаптера с явным именем."""
        manager = ConcreteManager("TestManager")
        adapter = Mock()
        adapter.__class__.__name__ = "TestAdapter"
        
        result = manager.attach_adapter(adapter, name="custom_adapter")
        
        assert result is True
        assert manager.has_adapter("custom_adapter") is True
        assert manager.get_adapter("custom_adapter") == adapter
        assert adapter.manager == manager  # Проверяем обратную ссылку
    
    def test_attach_adapter_without_name(self):
        """Тест подключения адаптера без явного имени (автоопределение - простая логика)."""
        manager = ConcreteManager("TestManager")
        adapter = Mock()
        adapter.__class__.__name__ = "CommandAdapter"
        
        result = manager.attach_adapter(adapter)
        
        assert result is True
        # Имя должно определиться автоматически как "command" (простая логика)
        assert manager.has_adapter("command") is True
        assert manager.get_adapter("command") == adapter
    
    def test_attach_adapter_none(self):
        """Тест подключения None адаптера (должен вернуть False)."""
        manager = ConcreteManager("TestManager")
        
        result = manager.attach_adapter(None)
        
        assert result is False
        assert len(manager.list_adapters()) == 0
    
    def test_attach_multiple_adapters(self):
        """Тест подключения нескольких адаптеров."""
        manager = ConcreteManager("TestManager")
        adapter1 = Mock()
        adapter1.__class__.__name__ = "CommandAdapter"
        adapter2 = Mock()
        adapter2.__class__.__name__ = "LoggerAdapter"
        
        manager.attach_adapter(adapter1, name="command")
        manager.attach_adapter(adapter2, name="logger")
        
        assert len(manager.list_adapters()) == 2
        assert "command" in manager.list_adapters()
        assert "logger" in manager.list_adapters()
        assert manager.get_adapter("command") == adapter1
        assert manager.get_adapter("logger") == adapter2
    
    def test_get_adapter_by_name(self):
        """Тест получения адаптера по имени."""
        manager = ConcreteManager("TestManager")
        adapter = Mock()
        adapter.__class__.__name__ = "TestAdapter"
        
        manager.attach_adapter(adapter, name="test")
        
        retrieved = manager.get_adapter("test")
        assert retrieved == adapter
    
    def test_get_adapter_without_name(self):
        """Тест получения адаптера без указания имени (первый адаптер)."""
        manager = ConcreteManager("TestManager")
        adapter1 = Mock()
        adapter1.__class__.__name__ = "Adapter1"
        adapter2 = Mock()
        adapter2.__class__.__name__ = "Adapter2"
        
        manager.attach_adapter(adapter1, name="first")
        manager.attach_adapter(adapter2, name="second")
        
        # Должен вернуться первый не-None адаптер
        retrieved = manager.get_adapter()
        assert retrieved in [adapter1, adapter2]
    
    def test_get_adapter_nonexistent(self):
        """Тест получения несуществующего адаптера."""
        manager = ConcreteManager("TestManager")
        
        retrieved = manager.get_adapter("nonexistent")
        assert retrieved is None
    
    def test_get_adapter_empty(self):
        """Тест получения адаптера когда их нет."""
        manager = ConcreteManager("TestManager")
        
        retrieved = manager.get_adapter()
        assert retrieved is None
    
    def test_has_adapter_existing(self):
        """Тест проверки наличия существующего адаптера."""
        manager = ConcreteManager("TestManager")
        adapter = Mock()
        adapter.__class__.__name__ = "TestAdapter"
        
        manager.attach_adapter(adapter, name="test")
        
        assert manager.has_adapter("test") is True
    
    def test_has_adapter_nonexistent(self):
        """Тест проверки наличия несуществующего адаптера."""
        manager = ConcreteManager("TestManager")
        
        assert manager.has_adapter("nonexistent") is False
    
    def test_list_adapters_empty(self):
        """Тест получения списка адаптеров когда их нет."""
        manager = ConcreteManager("TestManager")
        
        adapters = manager.list_adapters()
        assert adapters == []
    
    def test_list_adapters_multiple(self):
        """Тест получения списка нескольких адаптеров."""
        manager = ConcreteManager("TestManager")
        adapter1 = Mock()
        adapter1.__class__.__name__ = "Adapter1"
        adapter2 = Mock()
        adapter2.__class__.__name__ = "Adapter2"
        adapter3 = Mock()
        adapter3.__class__.__name__ = "Adapter3"
        
        manager.attach_adapter(adapter1, name="first")
        manager.attach_adapter(adapter2, name="second")
        manager.attach_adapter(adapter3, name="third")
        
        adapters = manager.list_adapters()
        assert len(adapters) == 3
        assert "first" in adapters
        assert "second" in adapters
        assert "third" in adapters
    
    def test_detach_adapter_existing(self):
        """Тест отключения существующего адаптера."""
        manager = ConcreteManager("TestManager")
        adapter = Mock()
        adapter.__class__.__name__ = "TestAdapter"
        
        manager.attach_adapter(adapter, name="test")
        assert manager.has_adapter("test") is True
        
        result = manager.detach_adapter("test")
        
        assert result is True
        assert manager.has_adapter("test") is False
        assert manager.get_adapter("test") is None
    
    def test_detach_adapter_nonexistent(self):
        """Тест отключения несуществующего адаптера."""
        manager = ConcreteManager("TestManager")
        
        result = manager.detach_adapter("nonexistent")
        
        assert result is False
    
    def test_detach_adapter_multiple(self):
        """Тест отключения одного адаптера из нескольких."""
        manager = ConcreteManager("TestManager")
        adapter1 = Mock()
        adapter1.__class__.__name__ = "Adapter1"
        adapter2 = Mock()
        adapter2.__class__.__name__ = "Adapter2"
        
        manager.attach_adapter(adapter1, name="first")
        manager.attach_adapter(adapter2, name="second")
        
        manager.detach_adapter("first")
        
        assert manager.has_adapter("first") is False
        assert manager.has_adapter("second") is True
        assert len(manager.list_adapters()) == 1
    
    # ========== Тесты для __getattr__ magic-доступа ==========
    
    def test_getattr_adapter_by_name(self):
        """Тест magic-доступа к адаптеру по имени."""
        manager = ConcreteManager("TestManager")
        adapter = Mock()
        adapter.__class__.__name__ = "CommandAdapter"
        
        manager.attach_adapter(adapter, name="command")
        
        # Доступ через magic-атрибут
        retrieved = manager.command
        assert retrieved == adapter
    
    def test_getattr_adapter_by_class_name(self):
        """Тест magic-доступа к адаптеру по имени класса (snake_case)."""
        manager = ConcreteManager("TestManager")
        adapter = Mock()
        adapter.__class__.__name__ = "CommandAdapter"
        
        manager.attach_adapter(adapter)
        # Имя определится как "command"
        
        # Доступ через magic-атрибут
        retrieved = manager.command
        assert retrieved == adapter
    
    def test_getattr_adapter_nonexistent(self):
        """Тест magic-доступа к несуществующему адаптеру."""
        manager = ConcreteManager("TestManager")
        
        with pytest.raises(AttributeError) as exc_info:
            _ = manager.nonexistent_adapter
        
        assert "has no attribute 'nonexistent_adapter'" in str(exc_info.value)
    
    def test_getattr_adapter_none_value(self):
        """Тест magic-доступа когда адаптер равен None."""
        manager = ConcreteManager("TestManager")
        # Устанавливаем None адаптер напрямую (не через attach_adapter)
        manager._adapters["test"] = None
        
        with pytest.raises(AttributeError) as exc_info:
            _ = manager.test
        
        assert "has no attribute 'test'" in str(exc_info.value)
        assert "adapter is None" in str(exc_info.value)
    
    def test_getattr_complex_class_names(self):
        """Тест magic-доступа с различными именами классов."""
        manager = ConcreteManager("TestManager")
        
        # Тест с ProcessIntegrationAdapter -> process_integration
        adapter1 = Mock()
        adapter1.__class__.__name__ = "ProcessIntegrationAdapter"
        manager.attach_adapter(adapter1)
        
        retrieved = manager.process_integration
        assert retrieved == adapter1
        
        # Тест с SimpleAdapter -> simple
        adapter2 = Mock()
        adapter2.__class__.__name__ = "SimpleAdapter"
        manager.attach_adapter(adapter2)
        
        retrieved = manager.simple
        assert retrieved == adapter2
    
    # ========== Тесты для _get_adapter_name_from_class ==========
    
    def test_get_adapter_name_from_class_with_adapter_suffix(self):
        """Тест определения имени адаптера с суффиксом 'Adapter'."""
        manager = ConcreteManager("TestManager")
        
        # CommandAdapter -> command
        name = manager._get_adapter_name_from_class("CommandAdapter")
        assert name == "command"
        
        # LoggerAdapter -> logger
        name = manager._get_adapter_name_from_class("LoggerAdapter")
        assert name == "logger"
    
    def test_get_adapter_name_from_class_without_adapter_suffix(self):
        """Тест определения имени адаптера без суффикса 'Adapter'."""
        manager = ConcreteManager("TestManager")
        
        # Command -> command
        name = manager._get_adapter_name_from_class("Command")
        assert name == "command"
    
    def test_get_adapter_name_from_class_pascal_case(self):
        """Тест конвертации PascalCase в snake_case (простая логика)."""
        manager = ConcreteManager("TestManager")
        
        # ProcessIntegrationAdapter -> process_integration
        name = manager._get_adapter_name_from_class("ProcessIntegrationAdapter")
        assert name == "process_integration"
        
        # SimpleAdapter -> simple
        name = manager._get_adapter_name_from_class("SimpleAdapter")
        assert name == "simple"
        
        # HTTPClientAdapter -> httpclient (простая логика, без обработки аббревиатур)
        # Для точного результата рекомендуется указывать имя явно
        name = manager._get_adapter_name_from_class("HTTPClientAdapter")
        assert name == "httpclient"  # Простая логика: HTTPClient -> httpclient
    
    def test_get_adapter_name_from_class_single_word(self):
        """Тест определения имени для однословного класса."""
        manager = ConcreteManager("TestManager")
        
        # Adapter -> (пустая строка после удаления суффикса)
        name = manager._get_adapter_name_from_class("Adapter")
        assert name == ""
    
    def test_get_adapter_name_from_class_empty_string(self):
        """Тест определения имени для пустой строки."""
        manager = ConcreteManager("TestManager")
        
        name = manager._get_adapter_name_from_class("")
        assert name == ""
    
    def test_get_adapter_name_from_class_complex_cases(self):
        """Тест определения имени для сложных случаев (простая логика)."""
        manager = ConcreteManager("TestManager")
        
        # XMLParserAdapter -> xmlparser (простая логика)
        # Для точного результата рекомендуется указывать имя явно: attach_adapter(adapter, name="xml_parser")
        name = manager._get_adapter_name_from_class("XMLParserAdapter")
        assert name == "xmlparser"
        
        # RESTAPIClientAdapter -> restapiclient (простая логика)
        # Для точного результата рекомендуется указывать имя явно: attach_adapter(adapter, name="rest_api_client")
        name = manager._get_adapter_name_from_class("RESTAPIClientAdapter")
        assert name == "restapiclient"
    
    # ========== Тесты для get_stats с адаптерами ==========
    
    def test_get_stats_with_adapters(self):
        """Тест получения статистики с адаптерами."""
        manager = ConcreteManager("TestManager")
        adapter1 = Mock()
        adapter1.__class__.__name__ = "Adapter1"
        adapter1.get_stats = Mock(return_value={"adapter_name": "Adapter1", "initialized": True})
        
        adapter2 = Mock()
        adapter2.__class__.__name__ = "Adapter2"
        adapter2.get_stats = Mock(return_value={"adapter_name": "Adapter2", "initialized": False})
        
        manager.attach_adapter(adapter1, name="first")
        manager.attach_adapter(adapter2, name="second")
        
        stats = manager.get_stats()
        
        assert "adapters" in stats
        assert "first" in stats["adapters"]
        assert "second" in stats["adapters"]
        assert "adapters_info" in stats
        assert "first" in stats["adapters_info"]
        assert "second" in stats["adapters_info"]
        assert stats["adapters_info"]["first"]["adapter_name"] == "Adapter1"
    
    def test_get_stats_with_adapters_without_get_stats(self):
        """Тест получения статистики с адаптерами без метода get_stats."""
        manager = ConcreteManager("TestManager")
        # Создаем простой объект без метода get_stats (не Mock, чтобы избежать автогенерации методов)
        class SimpleAdapter:
            pass
        
        adapter = SimpleAdapter()
        adapter.__class__.__name__ = "Adapter"
        
        manager.attach_adapter(adapter, name="test")
        
        stats = manager.get_stats()
        
        assert "adapters_info" in stats
        assert "test" in stats["adapters_info"]
        # Если метод get_stats отсутствует, должен вернуться пустой словарь
        assert stats["adapters_info"]["test"] == {}

