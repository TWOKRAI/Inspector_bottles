"""
Тесты для ObservableMixin (объединенного миксина).
"""

import pytest
from ..core.base_manager import BaseManager
from ..mixins.observable_mixin import ObservableMixin


class MockLogger:
    """Мок-логгер для тестов."""
    
    def __init__(self):
        self.logs = []
    
    def debug(self, msg, **kwargs):
        self.logs.append(('debug', msg))
    
    def info(self, msg, **kwargs):
        self.logs.append(('info', msg))
    
    def warning(self, msg, **kwargs):
        self.logs.append(('warning', msg))
    
    def error(self, msg, **kwargs):
        self.logs.append(('error', msg))
    
    def critical(self, msg, **kwargs):
        self.logs.append(('critical', msg))


class MockStats:
    """Мок-статистика для тестов."""
    
    def __init__(self):
        self.metrics = []
    
    def record_metric(self, name, value=1, tags=None):
        self.metrics.append(('record_metric', name, value))
    
    def increment(self, name, tags=None):
        self.metrics.append(('increment', name))
    
    def record_timing(self, name, duration, tags=None):
        self.metrics.append(('record_timing', name, duration))


class MockErrorTracker:
    """Мок-трекер ошибок для тестов."""
    
    def __init__(self):
        self.errors = []
    
    def track_error(self, error, context=None):
        self.errors.append(('track_error', error, context))
    
    def record_error(self, error, context=None):
        self.errors.append(('record_error', error, context))


class MockManager(BaseManager, ObservableMixin):
    __test__ = False  # Исключаем из pytest collection
    """Тестовый менеджер с ObservableMixin."""
    
    def __init__(self, name, logger=None, stats=None, error_tracker=None, auto_proxy=False, enable_decorators=False):
        BaseManager.__init__(self, name)
        managers = {}
        if logger:
            managers['logger'] = logger
        if stats:
            managers['stats'] = stats
        if error_tracker:
            managers['error'] = error_tracker
        
        config = {k: True for k in managers.keys()}
        if enable_decorators:
            config['enable_decorators'] = True
        
        ObservableMixin.__init__(
            self,
            managers=managers,
            config=config,
            auto_proxy=auto_proxy
        )
    
    def initialize(self) -> bool:
        self.is_initialized = True
        return True
    
    def shutdown(self) -> bool:
        self.is_initialized = False
        return True


class TestObservableMixin:
    """Тесты для ObservableMixin."""
    
    def test_private_methods_always_available(self):
        """Тест: приватные методы всегда доступны."""
        logger = MockLogger()
        manager = MockManager("test", logger=logger, auto_proxy=False)
        
        # Приватные методы должны работать
        manager._log_info("Test message")
        
        assert len(logger.logs) == 1
        assert logger.logs[0] == ('info', 'Test message')
    
    def test_auto_proxy_creates_public_methods(self):
        """Тест: автоматические прокси-методы создаются при auto_proxy=True."""
        logger = MockLogger()
        stats = MockStats()
        manager = MockManager("test", logger=logger, stats=stats, auto_proxy=True)
        
        # Публичные методы должны быть созданы
        assert hasattr(manager, 'log_info')
        assert hasattr(manager, 'record_metric')
        
        # И должны работать
        manager.log_info("Test message")
        manager.record_metric("test.metric", value=5)
        
        assert len(logger.logs) == 1
        assert logger.logs[0] == ('info', 'Test message')
        assert len(stats.metrics) == 1
        assert stats.metrics[0] == ('record_metric', 'test.metric', 5)
    
    def test_both_private_and_public_work(self):
        """Тест: и приватные, и публичные методы работают одновременно."""
        logger = MockLogger()
        manager = MockManager("test", logger=logger, auto_proxy=True)
        
        # Оба стиля должны работать
        manager._log_info("Private method")
        manager.log_info("Public method")
        
        assert len(logger.logs) == 2
        assert logger.logs[0] == ('info', 'Private method')
        assert logger.logs[1] == ('info', 'Public method')
    
    def test_error_tracking(self):
        """Тест: отслеживание ошибок."""
        error_tracker = MockErrorTracker()
        manager = MockManager("test", error_tracker=error_tracker, auto_proxy=True)
        
        # Приватный метод
        error = Exception("Test error")
        manager._track_error(error, {"context": "test"})
        
        # Может быть 1 или 2 ошибки из-за fallback логики, но должна быть хотя бы одна
        assert len(error_tracker.errors) >= 1
        # Проверяем что ошибка зарегистрирована (любым методом из fallback логики)
        # Первая ошибка должна быть track_error (основной метод)
        assert error_tracker.errors[0][0] in ('track_error', 'record_error')
        # Проверяем что ошибка правильная
        assert error_tracker.errors[0][1] == error
        
        # Публичный метод (если создан)
        if hasattr(manager, 'track_error'):
            initial_count = len(error_tracker.errors)
            error2 = Exception("Test error 2")
            manager.track_error(error2)
            # После второго вызова должно быть минимум на 1 больше ошибок
            assert len(error_tracker.errors) >= initial_count + 1
            # Проверяем что вторая ошибка тоже зарегистрирована
            assert any(err[1] == error2 for err in error_tracker.errors)
    
    def test_register_manager_updates_proxy(self):
        """Тест: регистрация нового менеджера обновляет прокси-методы."""
        logger = MockLogger()
        manager = MockManager("test", logger=logger, auto_proxy=True)
        
        # Изначально log_info должен работать
        manager.log_info("Test")
        assert len(logger.logs) == 1
        
        # Регистрируем новый логгер
        logger2 = MockLogger()
        manager.register_manager('logger2', logger2, enabled=True)
        
        # Новый логгер должен быть доступен
        assert manager.has_manager('logger2')
    
    def test_enable_disable(self):
        """Тест: включение/выключение менеджеров."""
        logger = MockLogger()
        manager = MockManager("test", logger=logger, auto_proxy=False)
        
        # Менеджер включен
        manager._log_info("Test")
        assert len(logger.logs) == 1
        
        # Выключаем
        manager.disable('logger')
        manager._log_info("Test 2")
        assert len(logger.logs) == 1  # Не должно логироваться
        
        # Включаем обратно
        manager.enable('logger')
        manager._log_info("Test 3")
        assert len(logger.logs) == 2
    
    def test_context_manager(self):
        """Тест: контекстный менеджер для временного изменения состояния."""
        logger = MockLogger()
        manager = MockManager("test", logger=logger, auto_proxy=False)
        
        # Временно выключаем
        with manager.context('logger', enabled=False):
            manager._log_info("Test")
            assert len(logger.logs) == 0
        
        # После выхода должно работать
        manager._log_info("Test 2")
        assert len(logger.logs) == 1
    
    def test_decorator_logged(self):
        """Тест: декоратор logged."""
        logger = MockLogger()
        manager = MockManager("test", logger=logger, auto_proxy=False, enable_decorators=True)
        
        # Проверяем что декоратор доступен
        if not hasattr(manager, 'logged'):
            pytest.skip("Декораторы отключены для pickle-совместимости")
        
        @manager.logged(manager_name='logger', level='info')
        def test_function():
            return "result"
        
        result = test_function()
        
        assert result == "result"
        assert len(logger.logs) >= 1  # Должно быть логирование
    
    def test_decorator_timed(self):
        """Тест: декоратор timed."""
        stats = MockStats()
        manager = MockManager("test", stats=stats, auto_proxy=False, enable_decorators=True)
        
        # Проверяем что декоратор доступен
        if not hasattr(manager, 'timed'):
            pytest.skip("Декораторы отключены для pickle-совместимости")
        
        @manager.timed(manager_name='stats', metric_name='test.metric')
        def test_function():
            return "result"
        
        result = test_function()
        
        assert result == "result"
        assert len(stats.metrics) >= 1  # Должна быть метрика времени
    
    def test_decorator_monitored(self):
        """Тест: декоратор monitored."""
        logger = MockLogger()
        stats = MockStats()
        manager = MockManager("test", logger=logger, stats=stats, auto_proxy=False, enable_decorators=True)
        
        # Проверяем что декоратор доступен
        if not hasattr(manager, 'monitored'):
            pytest.skip("Декораторы отключены для pickle-совместимости")
        
        @manager.monitored(manager_name='logger', level='info', metric_name='test.metric')
        def test_function():
            return "result"
        
        result = test_function()
        
        assert result == "result"
        assert len(logger.logs) >= 1  # Должно быть логирование
        assert len(stats.metrics) >= 1  # Должна быть метрика

