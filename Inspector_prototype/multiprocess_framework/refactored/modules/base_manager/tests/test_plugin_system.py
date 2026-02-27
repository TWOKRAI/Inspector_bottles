"""
Тесты для плагин-системы ObservableMixin.
"""

import sys
from pathlib import Path

# Добавляем путь к модулю
src_path = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(src_path))

from multiprocess_framework.refactored.modules.base_manager.core.base_manager import BaseManager
from multiprocess_framework.refactored.modules.base_manager.mixins.observable_mixin import ObservableMixin
from multiprocess_framework.refactored.modules.base_manager.mixins.plugins.plugin_base import ObservablePlugin


class MockCustomManager:
    """Мок кастомного менеджера."""
    
    def __init__(self):
        self.calls = []
    
    def custom_method(self, arg):
        self.calls.append(('custom_method', arg))
        return f"result_{arg}"
    
    def another_method(self, data):
        self.calls.append(('another_method', data))
        return True


class CustomManagerPlugin(ObservablePlugin):
    """Тестовый плагин для кастомного менеджера."""
    
    def get_manager_names(self) -> list[str]:
        return ['custom_manager']
    
    def create_proxy_methods(self, instance, managers, call_manager_func):
        if 'custom_manager' in managers:
            instance.custom_call = lambda arg: call_manager_func('custom_manager', 'custom_method', arg)
            instance.another_call = lambda data: call_manager_func('custom_manager', 'another_method', data)
    
    def create_private_methods(self, instance, call_manager_func):
        instance._custom_private = lambda arg: call_manager_func('custom_manager', 'custom_method', arg)


class MockManager(BaseManager, ObservableMixin):
    """Тестовый менеджер."""
    
    def __init__(self, name, custom_manager=None, plugins=None):
        BaseManager.__init__(self, name)
        managers = {}
        if custom_manager:
            managers['custom_manager'] = custom_manager
        
        ObservableMixin.__init__(
            self,
            managers=managers,
            plugins=plugins or []
        )
    
    def initialize(self) -> bool:
        return True
    
    def shutdown(self) -> bool:
        return True


def test_plugin_registration():
    """Тест: регистрация плагина."""
    custom_manager = MockCustomManager()
    plugin = CustomManagerPlugin()
    manager = MockManager("test", custom_manager=custom_manager, plugins=[plugin])
    
    # Плагин должен быть зарегистрирован
    assert manager.has_plugin('CustomManagerPlugin')
    print("[OK] test_plugin_registration passed")


def test_plugin_proxy_methods():
    """Тест: прокси-методы из плагина."""
    custom_manager = MockCustomManager()
    plugin = CustomManagerPlugin()
    manager = MockManager("test", custom_manager=custom_manager, plugins=[plugin])
    
    # Включаем auto_proxy для создания прокси-методов
    manager._create_proxy_methods()
    
    # Прокси-методы должны быть созданы
    assert hasattr(manager, 'custom_call')
    assert hasattr(manager, 'another_call')
    
    # И должны работать
    result = manager.custom_call("test_arg")
    assert result == "result_test_arg"
    assert len(custom_manager.calls) == 1
    assert custom_manager.calls[0] == ('custom_method', 'test_arg')
    print("[OK] test_plugin_proxy_methods passed")


def test_plugin_private_methods():
    """Тест: приватные методы из плагина."""
    custom_manager = MockCustomManager()
    plugin = CustomManagerPlugin()
    manager = MockManager("test", custom_manager=custom_manager, plugins=[plugin])
    
    # Приватные методы должны быть созданы
    assert hasattr(manager, '_custom_private')
    
    # И должны работать
    result = manager._custom_private("test_arg")
    assert result == "result_test_arg"
    print("[OK] test_plugin_private_methods passed")


def test_dynamic_plugin_registration():
    """Тест: динамическая регистрация плагина."""
    custom_manager = MockCustomManager()
    manager = MockManager("test", custom_manager=custom_manager)
    
    # Плагин еще не зарегистрирован
    assert not manager.has_plugin('CustomManagerPlugin')
    assert not hasattr(manager, 'custom_call')
    
    # Включаем auto_proxy
    manager._create_proxy_methods()
    
    # Регистрируем плагин
    plugin = CustomManagerPlugin()
    manager.register_plugin(plugin)
    
    # Теперь плагин зарегистрирован и методы доступны
    assert manager.has_plugin('CustomManagerPlugin')
    assert hasattr(manager, 'custom_call')
    
    # Методы работают
    result = manager.custom_call("test")
    assert result == "result_test"
    print("[OK] test_dynamic_plugin_registration passed")


def test_multiple_plugins():
    """Тест: несколько плагинов."""
    class Plugin1(ObservablePlugin):
        def get_manager_names(self):
            return ['manager1']
        def create_proxy_methods(self, instance, managers, call_manager_func):
            if 'manager1' in managers:
                instance.method1 = lambda: call_manager_func('manager1', 'method1')
    
    class Plugin2(ObservablePlugin):
        def get_manager_names(self):
            return ['manager2']
        def create_proxy_methods(self, instance, managers, call_manager_func):
            if 'manager2' in managers:
                instance.method2 = lambda: call_manager_func('manager2', 'method2')
    
    manager1 = MockCustomManager()
    manager2 = MockCustomManager()
    
    manager = MockManager(
        "test",
        custom_manager=manager1,
        plugins=[Plugin1(), Plugin2()]
    )
    
    # Оба плагина должны быть зарегистрированы
    assert manager.has_plugin('Plugin1')
    assert manager.has_plugin('Plugin2')
    print("[OK] test_multiple_plugins passed")


def test_plugin_with_auto_proxy():
    """Тест: плагин с auto_proxy=True."""
    custom_manager = MockCustomManager()
    plugin = CustomManagerPlugin()
    
    manager = MockManager("test", custom_manager=custom_manager, plugins=[plugin])
    
    # Включаем auto_proxy
    manager._create_proxy_methods()
    
    # Прокси-методы должны быть доступны
    assert hasattr(manager, 'custom_call')
    result = manager.custom_call("test")
    assert result == "result_test"
    print("[OK] test_plugin_with_auto_proxy passed")


if __name__ == "__main__":
    print("=" * 60)
    print("Запуск тестов плагин-системы ObservableMixin")
    print("=" * 60)
    print()
    
    try:
        test_plugin_registration()
        test_plugin_proxy_methods()
        test_plugin_private_methods()
        test_dynamic_plugin_registration()
        test_multiple_plugins()
        test_plugin_with_auto_proxy()
        
        print()
        print("=" * 60)
        print("[SUCCESS] ALL PLUGIN TESTS PASSED!")
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

