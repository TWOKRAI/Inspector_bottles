"""
Простые тесты импортов и базовой структуры.

Проверяют, что все модули корректно импортируются и структура правильная.
"""

import sys
import os

# Добавляем путь к проекту
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


def test_imports():
    """Тест импортов всех компонентов"""
    print("Testing imports...")
    
    try:
        from multiprocess_framework.modules.Process_module.core import ProcessCore
        print("✓ ProcessCore imported")
    except Exception as e:
        print(f"✗ ProcessCore import failed: {e}")
        assert False, f"ProcessCore import failed: {e}"
    
    try:
        from multiprocess_framework.modules.Process_module.config_handler import ProcessConfigHandler
        print("✓ ProcessConfigHandler imported")
    except Exception as e:
        print(f"✗ ProcessConfigHandler import failed: {e}")
        assert False, f"ProcessConfigHandler import failed: {e}"
    
    try:
        from multiprocess_framework.modules.Process_module.managers import ProcessManagers
        print("✓ ProcessManagers imported")
    except Exception as e:
        print(f"✗ ProcessManagers import failed: {e}")
        assert False, f"ProcessManagers import failed: {e}"
    
    try:
        from multiprocess_framework.modules.Process_module.communication import ProcessCommunication
        print("✓ ProcessCommunication imported")
    except Exception as e:
        print(f"✗ ProcessCommunication import failed: {e}")
        assert False, f"ProcessCommunication import failed: {e}"
    
    try:
        from multiprocess_framework.modules.Process_module.process_module import ProcessModule
        print("✓ ProcessModule imported")
    except Exception as e:
        print(f"✗ ProcessModule import failed: {e}")
        assert False, f"ProcessModule import failed: {e}"
    
    try:
        from multiprocess_framework.modules.Process_module import (
            ProcessModule,
            ProcessCore,
            ProcessConfigHandler,
            ProcessManagers,
            ProcessCommunication
        )
        print("✓ All components imported from __init__.py")
    except Exception as e:
        print(f"✗ __init__.py import failed: {e}")
        assert False, f"__init__.py import failed: {e}"


def test_structure():
    """Тест структуры классов"""
    print("\nTesting class structure...")
    
    from multiprocess_framework.modules.Process_module.core import ProcessCore
    from multiprocess_framework.modules.Process_module.config_handler import ProcessConfigHandler
    from multiprocess_framework.modules.Process_module.managers import ProcessManagers
    from multiprocess_framework.modules.Process_module.communication import ProcessCommunication
    from multiprocess_framework.modules.Process_module.process_module import ProcessModule
    
    # Проверяем ProcessCore
    assert hasattr(ProcessCore, '__init__'), "ProcessCore should have __init__"
    assert hasattr(ProcessCore, 'run'), "ProcessCore should have run"
    assert hasattr(ProcessCore, 'stop'), "ProcessCore should have stop"
    assert hasattr(ProcessCore, 'should_stop'), "ProcessCore should have should_stop"
    print("✓ ProcessCore structure OK")
    
    # Проверяем ProcessConfigHandler
    assert hasattr(ProcessConfigHandler, '__init__'), "ProcessConfigHandler should have __init__"
    assert hasattr(ProcessConfigHandler, 'get_managers_config'), "ProcessConfigHandler should have get_managers_config"
    assert hasattr(ProcessConfigHandler, 'update_config'), "ProcessConfigHandler should have update_config"
    print("✓ ProcessConfigHandler structure OK")
    
    # Проверяем ProcessManagers
    assert hasattr(ProcessManagers, '__init__'), "ProcessManagers should have __init__"
    assert hasattr(ProcessManagers, 'initialize_core_managers'), "ProcessManagers should have initialize_core_managers"
    assert hasattr(ProcessManagers, 'reload_manager'), "ProcessManagers should have reload_manager"
    print("✓ ProcessManagers structure OK")
    
    # Проверяем ProcessCommunication
    assert hasattr(ProcessCommunication, '__init__'), "ProcessCommunication should have __init__"
    assert hasattr(ProcessCommunication, 'send'), "ProcessCommunication should have send"
    assert hasattr(ProcessCommunication, 'receive'), "ProcessCommunication should have receive"
    print("✓ ProcessCommunication structure OK")
    
    # Проверяем ProcessModule
    assert hasattr(ProcessModule, '__init__'), "ProcessModule should have __init__"
    assert hasattr(ProcessModule, 'run'), "ProcessModule should have run"
    assert hasattr(ProcessModule, 'stop'), "ProcessModule should have stop"
    assert hasattr(ProcessModule, 'send'), "ProcessModule should have send"
    assert hasattr(ProcessModule, 'receive'), "ProcessModule should have receive"
    print("✓ ProcessModule structure OK")
    
    # Проверяем, что ProcessModule наследуется от ProcessCore
    assert issubclass(ProcessModule, ProcessCore), "ProcessModule should inherit from ProcessCore"
    print("✓ ProcessModule inheritance OK")


def test_properties():
    """Тест свойств ProcessModule"""
    print("\nTesting ProcessModule properties...")
    
    from multiprocess_framework.modules.Process_module.process_module import ProcessModule
    
    # Проверяем наличие свойств
    properties = [
        'managers', 'adapters', 'worker_manager', 'logger_manager',
        'command_manager', 'router_manager', 'router',
        'logger_adapter', 'command_adapter', 'router_adapter'
    ]
    
    for prop in properties:
        assert hasattr(ProcessModule, prop), f"ProcessModule should have property {prop}"
    
    print("✓ All properties defined")


if __name__ == '__main__':
    print("=" * 60)
    print("Testing ProcessModule Structure")
    print("=" * 60)
    
    success = True
    
    try:
        test_imports()
        test_structure()
        test_properties()
        success = True
        
        print("\n" + "=" * 60)
        if success:
            print("✅ All structure tests passed!")
        else:
            print("❌ Some tests failed")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Error during testing: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    sys.exit(0 if success else 1)

