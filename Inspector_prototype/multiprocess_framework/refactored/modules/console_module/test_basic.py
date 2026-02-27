"""
Базовый тест для проверки работоспособности ConsoleModule.
"""
import sys
import os

# Добавляем путь к корню проекта
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../../')))

from multiprocess_framework.refactored.modules.console_module import (
    ConsoleManager,
    ConsoleChannel,
    ConsoleRedirector
)
from unittest.mock import Mock

def test_imports():
    """Тест импортов."""
    print("✓ Импорты успешны")

def test_console_manager_init():
    """Тест инициализации ConsoleManager."""
    manager = ConsoleManager(
        manager_name="TestConsole",
        enabled=False
    )
    assert manager.manager_name == "TestConsole"
    assert not manager.is_console_enabled()
    print("✓ ConsoleManager инициализирован")

def test_console_manager_lifecycle():
    """Тест жизненного цикла ConsoleManager."""
    manager = ConsoleManager(
        manager_name="TestConsole",
        enabled=True
    )
    
    # Инициализация
    result = manager.initialize()
    assert result == True
    assert manager.is_initialized == True
    print("✓ ConsoleManager.initialize() работает")
    
    # Завершение
    result = manager.shutdown()
    assert result == True
    assert manager.is_initialized == False
    print("✓ ConsoleManager.shutdown() работает")

def test_console_manager_enable():
    """Тест включения/выключения консоли."""
    manager = ConsoleManager(
        manager_name="TestConsole"
    )
    manager.initialize()
    
    # Включить
    result = manager.enable_console(enabled=True)
    assert result == True
    assert manager.is_console_enabled() == True
    print("✓ enable_console(True) работает")
    
    # Выключить
    result = manager.enable_console(enabled=False)
    assert result == True
    assert manager.is_console_enabled() == False
    print("✓ enable_console(False) работает")
    
    manager.shutdown()

def test_console_manager_send_message():
    """Тест отправки сообщения."""
    manager = ConsoleManager(
        manager_name="TestConsole",
        enabled=True
    )
    manager.initialize()
    
    result = manager.send_message("Test message", level="INFO")
    assert result == True
    print("✓ send_message() работает")
    
    manager.shutdown()

def test_console_channel():
    """Тест ConsoleChannel."""
    console_manager = Mock()
    console_manager._send_to_console = Mock(return_value=True)
    
    channel = ConsoleChannel(
        name="console.Test",
        console_manager=console_manager,
        target_process="Test"
    )
    
    assert channel.name == "console.Test"
    assert channel.channel_type == "console"
    
    result = channel.send({'text': 'Test message'})
    assert result['status'] == 'success'
    print("✓ ConsoleChannel работает")

def test_console_redirector():
    """Тест ConsoleRedirector."""
    from multiprocessing import Queue
    
    queue = Queue()
    redirector = ConsoleRedirector(queue, "TestProcess")
    
    assert redirector.process_name == "TestProcess"
    assert len(redirector.output_queues) == 1
    
    redirector.write("Test\n")
    
    # Проверяем что сообщение попало в очередь
    stream_type, data = queue.get(timeout=1.0)
    assert stream_type == 'stdout'
    assert 'TestProcess' in data
    print("✓ ConsoleRedirector работает")

def test_console_manager_redirect():
    """Тест перенаправления."""
    manager = ConsoleManager(
        manager_name="TestConsole",
        enabled=True,
        redirect_enabled=False
    )
    manager.initialize()
    
    # Включить перенаправление
    result = manager.setup_redirect(enabled=True)
    assert result == True
    assert manager.is_redirect_enabled() == True
    print("✓ setup_redirect(True) работает")
    
    # Выключить перенаправление
    result = manager.setup_redirect(enabled=False)
    assert result == True
    assert manager.is_redirect_enabled() == False
    print("✓ setup_redirect(False) работает")
    
    manager.shutdown()

def main():
    """Запуск всех тестов."""
    print("=" * 60)
    print("Тестирование ConsoleModule")
    print("=" * 60)
    
    try:
        test_imports()
        test_console_manager_init()
        test_console_manager_lifecycle()
        test_console_manager_enable()
        test_console_manager_send_message()
        test_console_channel()
        test_console_redirector()
        test_console_manager_redirect()
        
        print("=" * 60)
        print("Все тесты пройдены успешно!")
        print("=" * 60)
        return 0
    except Exception as e:
        print(f"Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())

