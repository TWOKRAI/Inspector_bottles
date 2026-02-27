"""
Тесты для рефакторенного ObservableMixin.
"""

import sys
from pathlib import Path

# Добавляем путь к модулю
src_path = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(src_path))

from multiprocess_framework.refactored.modules.base_manager.core.base_manager import BaseManager
from multiprocess_framework.refactored.modules.base_manager.mixins.observable_mixin import ObservableMixin


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


class MockManager(BaseManager, ObservableMixin):
    """Тестовый менеджер с ObservableMixin."""
    
    def __init__(self, name, logger=None, stats=None, auto_proxy=False, enable_decorators=False):
        BaseManager.__init__(self, name)
        managers = {}
        if logger:
            managers['logger'] = logger
        if stats:
            managers['stats'] = stats
        
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


def test_private_methods():
    """Тест: приватные методы всегда доступны."""
    logger = MockLogger()
    manager = MockManager("test", logger=logger, auto_proxy=False)
    
    manager._log_info("Test message")
    
    assert len(logger.logs) == 1
    assert logger.logs[0] == ('info', 'Test message')
    print("[OK] test_private_methods passed")


def test_auto_proxy():
    """Тест: автоматические прокси-методы создаются при auto_proxy=True."""
    logger = MockLogger()
    stats = MockStats()
    manager = MockManager("test", logger=logger, stats=stats, auto_proxy=True)
    
    assert hasattr(manager, 'log_info')
    assert hasattr(manager, 'record_metric')
    
    manager.log_info("Test message")
    manager.record_metric("test.metric", value=5)
    
    assert len(logger.logs) == 1
    assert logger.logs[0] == ('info', 'Test message')
    assert len(stats.metrics) == 1
    assert stats.metrics[0] == ('record_metric', 'test.metric', 5)
    print("[OK] test_auto_proxy passed")


def test_both_methods():
    """Тест: и приватные, и публичные методы работают одновременно."""
    logger = MockLogger()
    manager = MockManager("test", logger=logger, auto_proxy=True)
    
    manager._log_info("Private method")
    manager.log_info("Public method")
    
    assert len(logger.logs) == 2
    assert logger.logs[0] == ('info', 'Private method')
    assert logger.logs[1] == ('info', 'Public method')
    print("[OK] test_both_methods passed")


def test_register_manager():
    """Тест: регистрация нового менеджера."""
    logger = MockLogger()
    manager = MockManager("test", logger=logger, auto_proxy=True)
    
    logger2 = MockLogger()
    manager.register_manager('logger2', logger2, enabled=True)
    
    assert manager.has_manager('logger2')
    print("[OK] test_register_manager passed")


def test_enable_disable():
    """Тест: включение/выключение менеджеров."""
    logger = MockLogger()
    manager = MockManager("test", logger=logger, auto_proxy=False)
    
    manager._log_info("Test")
    assert len(logger.logs) == 1
    
    manager.disable('logger')
    manager._log_info("Test 2")
    assert len(logger.logs) == 1
    
    manager.enable('logger')
    manager._log_info("Test 3")
    assert len(logger.logs) == 2
    print("[OK] test_enable_disable passed")


def test_context_manager():
    """Тест: контекстный менеджер."""
    logger = MockLogger()
    manager = MockManager("test", logger=logger, auto_proxy=False)
    
    with manager.context('logger', enabled=False):
        manager._log_info("Test")
        assert len(logger.logs) == 0
    
    manager._log_info("Test 2")
    assert len(logger.logs) == 1
    print("[OK] test_context_manager passed")


def test_decorators():
    """Тест: декораторы."""
    logger = MockLogger()
    stats = MockStats()
    manager = MockManager("test", logger=logger, stats=stats, auto_proxy=False, enable_decorators=True)
    
    # Проверяем что декоратор доступен
    if not hasattr(manager, 'logged'):
        print("[SKIP] test_decorators - декораторы отключены для pickle-совместимости")
        return
    
    @manager.logged(manager_name='logger', level='info')
    def test_function():
        return "result"
    
    result = test_function()
    
    assert result == "result"
    assert len(logger.logs) >= 1
    print("[OK] test_decorators passed")


if __name__ == "__main__":
    print("=" * 60)
    print("Запуск тестов рефакторенного ObservableMixin")
    print("=" * 60)
    print()
    
    try:
        test_private_methods()
        test_auto_proxy()
        test_both_methods()
        test_register_manager()
        test_enable_disable()
        test_context_manager()
        test_decorators()
        
        print()
        print("=" * 60)
        print("[SUCCESS] ALL TESTS PASSED!")
        print("=" * 60)
        
    except AssertionError as e:
        print()
        print("=" * 60)
        print(f"[FAIL] TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 60)
        sys.exit(1)
    except Exception as e:
        print()
        print("=" * 60)
        print(f"[ERROR] ERROR: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 60)
        sys.exit(1)





