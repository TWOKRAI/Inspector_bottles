"""
Интеграционные тесты для BaseManager и BaseAdapter.

Проверяют взаимодействие компонентов в реальных сценариях использования.
"""

import pytest
from multiprocess_framework.refactored.modules.base_manager import (
    BaseManager, BaseAdapter, ObservableMixin
)
from multiprocess_framework.refactored.modules.base_manager.interfaces import (
    IBaseManager, IBaseAdapter
)


# ============================================================================
# Вспомогательные классы для тестов
# ============================================================================

class TestManager(BaseManager):
    """Тестовый менеджер для проверки BaseManager."""
    
    def __init__(self, name: str, process=None):
        super().__init__(name, process)
        self._initialized_called = False
        self._shutdown_called = False
    
    def initialize(self) -> bool:
        """Инициализация менеджера."""
        self._initialized_called = True
        self.is_initialized = True
        return True
    
    def shutdown(self) -> bool:
        """Завершение работы менеджера."""
        self._shutdown_called = True
        self.is_initialized = False
        return True


class TestAdapter(BaseAdapter):
    """Тестовый адаптер для проверки BaseAdapter."""
    
    def __init__(self, manager, process=None):
        super().__init__(manager, process)
        self._setup_called = False
        self._operation_result = None
    
    def setup(self) -> bool:
        """Настройка адаптера."""
        self._setup_called = True
        self._initialized = True
        return True
    
    def do_something(self) -> str:
        """Тестовая операция."""
        self._operation_result = "done"
        return self._operation_result


class TestManagerWithObservable(BaseManager, ObservableMixin):
    """Тестовый менеджер с ObservableMixin."""
    
    def __init__(self, name: str, logger=None, stats=None, auto_proxy=False):
        BaseManager.__init__(self, name)
        managers = {}
        if logger:
            managers['logger'] = logger
        if stats:
            managers['stats'] = stats
        
        ObservableMixin.__init__(
            self,
            managers=managers,
            config={k: True for k in managers.keys()},
            auto_proxy=auto_proxy
        )
    
    def initialize(self) -> bool:
        self.is_initialized = True
        return True
    
    def shutdown(self) -> bool:
        self.is_initialized = False
        return True


class MockLogger:
    """Мок-логгер для тестов."""
    
    def __init__(self):
        self.logs = []
    
    def info(self, msg, **kwargs):
        self.logs.append(('info', msg))
    
    def debug(self, msg, **kwargs):
        self.logs.append(('debug', msg))
    
    def error(self, msg, **kwargs):
        self.logs.append(('error', msg))


class MockStats:
    """Мок-статистика для тестов."""
    
    def __init__(self):
        self.metrics = []
    
    def record_metric(self, name, value=1, tags=None):
        self.metrics.append(('record_metric', name, value))
    
    def increment(self, name, tags=None):
        self.metrics.append(('increment', name))


# ============================================================================
# Тесты интеграции BaseManager + BaseAdapter
# ============================================================================

class TestManagerAdapterIntegration:
    """Тесты интеграции BaseManager и BaseAdapter."""
    
    def test_manager_adapter_lifecycle(self):
        """Полный жизненный цикл менеджера с адаптером."""
        # Создание менеджера
        manager = TestManager("test_manager")
        assert manager.manager_name == "test_manager"
        assert manager.is_initialized is False
        
        # Создание адаптера
        adapter = TestAdapter(manager)
        assert adapter.manager == manager
        
        # Подключение адаптера
        assert manager.attach_adapter(adapter, name="test") is True
        assert manager.has_adapter("test") is True
        
        # Инициализация менеджера
        assert manager.initialize() is True
        assert manager.is_initialized is True
        assert manager._initialized_called is True
        
        # Настройка адаптера
        assert adapter.setup() is True
        assert adapter.is_initialized() is True
        assert adapter._setup_called is True
        
        # Использование адаптера через менеджер
        assert manager.test_adapter is not None
        result = manager.test_adapter.do_something()
        assert result == "done"
        assert adapter._operation_result == "done"
        
        # Статистика менеджера включает адаптер
        stats = manager.get_stats()
        assert stats["manager_name"] == "test_manager"
        assert stats["is_initialized"] is True
        assert "test" in stats["adapters"]
        assert "test" in stats.get("adapters_info", {})
        
        # Завершение работы
        assert manager.shutdown() is True
        assert manager.is_initialized is False
        assert manager._shutdown_called is True
    
    def test_multiple_adapters(self):
        """Подключение нескольких адаптеров."""
        manager = TestManager("test_manager")
        
        adapter1 = TestAdapter(manager)
        adapter2 = TestAdapter(manager)
        
        # Подключение адаптеров
        assert manager.attach_adapter(adapter1, name="adapter1") is True
        assert manager.attach_adapter(adapter2, name="adapter2") is True
        
        # Проверка наличия
        assert manager.has_adapter("adapter1") is True
        assert manager.has_adapter("adapter2") is True
        
        # Доступ к адаптерам
        assert manager.get_adapter("adapter1") == adapter1
        assert manager.get_adapter("adapter2") == adapter2
        
        # Magic-доступ
        assert manager.adapter1 == adapter1
        assert manager.adapter2 == adapter2
        
        # Список адаптеров
        adapters = manager.list_adapters()
        assert "adapter1" in adapters
        assert "adapter2" in adapters
        assert len(adapters) == 2
    
    def test_adapter_detachment(self):
        """Отключение адаптера от менеджера."""
        manager = TestManager("test_manager")
        adapter = TestAdapter(manager)
        
        # Подключение
        manager.attach_adapter(adapter, name="test")
        assert manager.has_adapter("test") is True
        
        # Отключение
        assert manager.detach_adapter("test") is True
        assert manager.has_adapter("test") is False
        
        # Попытка доступа после отключения
        assert manager.get_adapter("test") is None
    
    def test_manager_events(self):
        """События менеджера и обработка в адаптере."""
        manager = TestManager("test_manager")
        adapter = TestAdapter(manager)
        
        manager.attach_adapter(adapter, name="test")
        
        # Регистрация обработчика события
        event_called = []
        def handler(data):
            event_called.append(data)
        
        manager.on_event("test_event", handler)
        
        # Генерация события
        manager.emit_event("test_event", {"data": "test_value"})
        
        assert len(event_called) == 1
        assert event_called[0]["data"] == "test_value"
    
    def test_adapter_stats_in_manager_stats(self):
        """Статистика адаптера включается в статистику менеджера."""
        manager = TestManager("test_manager")
        adapter = TestAdapter(manager)
        
        manager.attach_adapter(adapter, name="test")
        adapter.setup()
        
        stats = manager.get_stats()
        
        # Проверка что статистика адаптера включена
        assert "adapters_info" in stats
        assert "test" in stats["adapters_info"]
        adapter_stats = stats["adapters_info"]["test"]
        assert adapter_stats["adapter_name"] == "test"
        assert adapter_stats["initialized"] is True
    
    def test_interface_compliance(self):
        """Проверка соответствия интерфейсам."""
        manager = TestManager("test_manager")
        adapter = TestAdapter(manager)
        
        # Проверка что менеджер реализует IBaseManager
        assert isinstance(manager, IBaseManager)
        assert hasattr(manager, 'initialize')
        assert hasattr(manager, 'shutdown')
        assert hasattr(manager, 'attach_adapter')
        assert hasattr(manager, 'get_adapter')
        
        # Проверка что адаптер реализует IBaseAdapter
        assert isinstance(adapter, IBaseAdapter)
        assert hasattr(adapter, 'setup')
        assert hasattr(adapter, 'is_initialized')


# ============================================================================
# Тесты интеграции ObservableMixin
# ============================================================================

class TestObservableMixinIntegration:
    """Тесты интеграции ObservableMixin с менеджерами."""
    
    def test_observable_mixin_with_managers(self):
        """Интеграция ObservableMixin с менеджерами."""
        logger = MockLogger()
        stats = MockStats()
        
        manager = TestManagerWithObservable(
            "test",
            logger=logger,
            stats=stats,
            auto_proxy=False
        )
        
        # Приватные методы работают
        manager._log_info("Test message")
        assert len(logger.logs) == 1
        assert logger.logs[0] == ('info', 'Test message')
        
        # Статистика работает
        manager._record_metric("test.metric", value=5)
        assert len(stats.metrics) == 1
        assert stats.metrics[0] == ('record_metric', 'test.metric', 5)
    
    def test_observable_mixin_auto_proxy(self):
        """Автоматические прокси-методы ObservableMixin."""
        logger = MockLogger()
        stats = MockStats()
        
        manager = TestManagerWithObservable(
            "test",
            logger=logger,
            stats=stats,
            auto_proxy=True
        )
        
        # Публичные методы созданы
        assert hasattr(manager, 'log_info')
        assert hasattr(manager, 'record_metric')
        
        # Публичные методы работают
        manager.log_info("Public log")
        assert len(logger.logs) == 1
        
        manager.record_metric("test.metric", value=10)
        assert len(stats.metrics) == 1
    
    def test_observable_mixin_enable_disable(self):
        """Включение/выключение менеджеров в ObservableMixin."""
        logger = MockLogger()
        manager = TestManagerWithObservable("test", logger=logger, auto_proxy=False)
        
        # Менеджер включен
        manager._log_info("Test 1")
        assert len(logger.logs) == 1
        
        # Выключаем
        manager.disable('logger')
        manager._log_info("Test 2")
        assert len(logger.logs) == 1  # Не увеличилось
        
        # Включаем обратно
        manager.enable('logger')
        manager._log_info("Test 3")
        assert len(logger.logs) == 2  # Увеличилось
    
    def test_observable_mixin_context_manager(self):
        """Контекстный менеджер для временного изменения состояния."""
        logger = MockLogger()
        manager = TestManagerWithObservable("test", logger=logger, auto_proxy=False)
        
        # Временно выключаем
        with manager.context('logger', enabled=False):
            manager._log_info("Test")
            assert len(logger.logs) == 0
        
        # После выхода должно работать
        manager._log_info("Test 2")
        assert len(logger.logs) == 1
    
    def test_observable_mixin_dynamic_registration(self):
        """Динамическая регистрация менеджера."""
        logger1 = MockLogger()
        manager = TestManagerWithObservable("test", logger=logger1, auto_proxy=True)
        
        # Изначальный логгер работает
        manager.log_info("Test 1")
        assert len(logger1.logs) == 1
        
        # Регистрируем новый логгер
        logger2 = MockLogger()
        manager.register_manager('logger2', logger2, enabled=True)
        
        # Новый логгер доступен
        assert manager.has_manager('logger2')
        
        # Старый логгер все еще работает
        manager.log_info("Test 2")
        assert len(logger1.logs) == 2


# ============================================================================
# Тесты полного workflow
# ============================================================================

class TestFullWorkflow:
    """Тесты полного workflow использования менеджера."""
    
    def test_complete_manager_workflow(self):
        """Полный workflow использования менеджера с ObservableMixin и адаптером."""
        # Создание менеджера с ObservableMixin
        logger = MockLogger()
        stats = MockStats()
        manager = TestManagerWithObservable(
            "test",
            logger=logger,
            stats=stats,
            auto_proxy=True
        )
        
        # Подключение адаптера
        adapter = TestAdapter(manager)
        manager.attach_adapter(adapter, name="test_adapter")
        
        # Инициализация
        assert manager.initialize() is True
        assert adapter.setup() is True
        
        # Использование всех возможностей
        
        # 1. Логирование через ObservableMixin
        manager.log_info("Processing started")
        assert len(logger.logs) == 1
        
        # 2. Статистика через ObservableMixin
        manager.record_metric("operations.count", value=1)
        assert len(stats.metrics) == 1
        
        # 3. Использование адаптера
        result = manager.test_adapter.do_something()
        assert result == "done"
        
        # 4. События
        event_called = []
        def handler(data):
            event_called.append(data)
        
        manager.on_event("processing_complete", handler)
        manager.emit_event("processing_complete", {"result": "success"})
        assert len(event_called) == 1
        
        # 5. Статистика
        stats_data = manager.get_stats()
        assert stats_data["manager_name"] == "test"
        assert stats_data["is_initialized"] is True
        assert "test_adapter" in stats_data["adapters"]
        
        # Завершение
        assert manager.shutdown() is True
        assert manager.is_initialized is False
    
    def test_manager_with_decorators(self):
        """Использование декораторов ObservableMixin."""
        logger = MockLogger()
        stats = MockStats()
        manager = TestManagerWithObservable(
            "test",
            logger=logger,
            stats=stats,
            auto_proxy=False
        )
        
        # Декоратор logged
        @manager.logged(manager_name='logger', level='info')
        def test_function():
            return "result"
        
        result = test_function()
        assert result == "result"
        assert len(logger.logs) >= 1
        
        # Декоратор timed
        @manager.timed(manager_name='stats', metric_name='test.metric')
        def timed_function():
            return "result"
        
        result = timed_function()
        assert result == "result"
        assert len(stats.metrics) >= 1
        
        # Декоратор monitored
        @manager.monitored(manager_name='logger', level='info', metric_name='test.metric')
        def monitored_function():
            return "result"
        
        result = monitored_function()
        assert result == "result"
        assert len(logger.logs) >= 2
        assert len(stats.metrics) >= 2


# ============================================================================
# Тесты обработки ошибок
# ============================================================================

class TestErrorScenarios:
    """Тесты сценариев с ошибками."""
    
    def test_manager_not_found_graceful_degradation(self):
        """Graceful degradation при отсутствии менеджера."""
        manager = TestManagerWithObservable("test", auto_proxy=False)
        
        # Вызов несуществующего менеджера через ObservableMixin
        # ObservableMixin имеет метод _call_manager
        if hasattr(manager, '_call_manager'):
            result = manager._call_manager('nonexistent', 'method')
            assert result is None  # Graceful degradation
        else:
            # Если метод не доступен, проверяем что менеджер не найден
            assert not manager.has_manager('nonexistent')
    
    def test_event_handler_error(self):
        """Ошибка в обработчике события не должна падать менеджер."""
        manager = TestManager("test_manager")
        
        # Обработчик с ошибкой
        def bad_handler(data):
            raise Exception("Error in handler")
        
        manager.on_event("test_event", bad_handler)
        
        # Не должно упасть
        manager.emit_event("test_event", {"data": "test"})
        # Если дошли сюда - тест прошел
    
    def test_none_adapter(self):
        """Обработка None адаптера."""
        manager = TestManager("test_manager")
        
        # Подключение None адаптера
        result = manager.attach_adapter(None, name="none")
        assert result is False  # Должен вернуть False
    
    def test_adapter_not_found(self):
        """Обработка отсутствующего адаптера."""
        manager = TestManager("test_manager")
        
        # Попытка получить несуществующий адаптер
        adapter = manager.get_adapter("nonexistent")
        assert adapter is None
        
        # Попытка magic-доступа
        with pytest.raises(AttributeError):
            _ = manager.nonexistent_adapter
    
    def test_manager_disabled(self):
        """Менеджер выключен - методы не вызываются."""
        logger = MockLogger()
        manager = TestManagerWithObservable("test", logger=logger, auto_proxy=False)
        
        # Выключаем менеджер
        manager.disable('logger')
        
        # Метод не должен вызываться
        manager._log_info("Test")
        assert len(logger.logs) == 0
        
        # Включаем обратно
        manager.enable('logger')
        manager._log_info("Test 2")
        assert len(logger.logs) == 1

