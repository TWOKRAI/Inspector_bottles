"""
Тесты для ConsoleManager.
"""
import unittest
import sys
import threading
import time
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from multiprocessing import Queue

# Добавляем путь к модулю для абсолютных импортов
module_path = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(module_path))

from src.multiprocess_framework.refactored.modules.console_module.core.console_manager import ConsoleManager


class TestConsoleManager(unittest.TestCase):
    """Тесты для ConsoleManager."""
    
    def setUp(self):
        """Подготовка к тестам."""
        self.manager_name = "TestConsoleManager"
        self.command_manager = Mock()
        self.router_manager = Mock()
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
    
    def tearDown(self):
        """Очистка после тестов."""
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr
    
    def test_init_default(self):
        """Тест инициализации с параметрами по умолчанию."""
        manager = ConsoleManager(
            manager_name=self.manager_name,
            command_manager=self.command_manager,
            router_manager=self.router_manager
        )
        
        self.assertEqual(manager.manager_name, self.manager_name)
        self.assertFalse(manager.is_console_enabled())
        self.assertFalse(manager.is_interactive())
        self.assertFalse(manager.is_redirect_enabled())
    
    def test_init_enabled(self):
        """Тест инициализации с включенной консолью."""
        manager = ConsoleManager(
            manager_name=self.manager_name,
            command_manager=self.command_manager,
            router_manager=self.router_manager,
            enabled=True
        )
        
        self.assertTrue(manager.is_console_enabled())
    
    def test_init_interactive(self):
        """Тест инициализации с интерактивным режимом."""
        manager = ConsoleManager(
            manager_name=self.manager_name,
            command_manager=self.command_manager,
            router_manager=self.router_manager,
            enabled=True,
            interactive=True
        )
        
        self.assertTrue(manager.is_interactive())
    
    def test_init_redirect(self):
        """Тест инициализации с перенаправлением."""
        manager = ConsoleManager(
            manager_name=self.manager_name,
            command_manager=self.command_manager,
            router_manager=self.router_manager,
            enabled=True,
            redirect_enabled=True
        )
        
        self.assertTrue(manager.is_redirect_enabled())
    
    def test_initialize(self):
        """Тест инициализации менеджера."""
        manager = ConsoleManager(
            manager_name=self.manager_name,
            command_manager=self.command_manager,
            router_manager=self.router_manager,
            enabled=True
        )
        
        result = manager.initialize()
        self.assertTrue(result)
        self.assertTrue(manager.is_initialized)
    
    def test_shutdown(self):
        """Тест завершения работы менеджера."""
        manager = ConsoleManager(
            manager_name=self.manager_name,
            command_manager=self.command_manager,
            router_manager=self.router_manager,
            enabled=True
        )
        
        manager.initialize()
        result = manager.shutdown()
        
        self.assertTrue(result)
        self.assertFalse(manager.is_initialized)
        self.assertFalse(manager.is_console_enabled())
    
    def test_enable_console(self):
        """Тест включения/выключения консоли."""
        manager = ConsoleManager(
            manager_name=self.manager_name,
            command_manager=self.command_manager,
            router_manager=self.router_manager
        )
        
        manager.initialize()
        
        # Включаем консоль
        result = manager.enable_console(enabled=True)
        self.assertTrue(result)
        self.assertTrue(manager.is_console_enabled())
        
        # Выключаем консоль
        result = manager.enable_console(enabled=False)
        self.assertTrue(result)
        self.assertFalse(manager.is_console_enabled())
    
    def test_send_message(self):
        """Тест отправки сообщения."""
        manager = ConsoleManager(
            manager_name=self.manager_name,
            command_manager=self.command_manager,
            router_manager=self.router_manager,
            enabled=True
        )
        
        manager.initialize()
        
        result = manager.send_message("Test message", level="INFO")
        self.assertTrue(result)
    
    def test_send_message_disabled(self):
        """Тест отправки сообщения при выключенной консоли."""
        manager = ConsoleManager(
            manager_name=self.manager_name,
            command_manager=self.command_manager,
            router_manager=self.router_manager
        )
        
        manager.initialize()
        
        result = manager.send_message("Test message")
        self.assertFalse(result)
    
    def test_setup_redirect(self):
        """Тест настройки перенаправления."""
        manager = ConsoleManager(
            manager_name=self.manager_name,
            command_manager=self.command_manager,
            router_manager=self.router_manager,
            enabled=True
        )
        
        manager.initialize()
        
        # Включаем перенаправление
        result = manager.setup_redirect(enabled=True)
        self.assertTrue(result)
        self.assertTrue(manager.is_redirect_enabled())
        
        # Выключаем перенаправление
        result = manager.setup_redirect(enabled=False)
        self.assertTrue(result)
        self.assertFalse(manager.is_redirect_enabled())
    
    def test_setup_redirect_without_console(self):
        """Тест настройки перенаправления без включенной консоли."""
        manager = ConsoleManager(
            manager_name=self.manager_name,
            command_manager=self.command_manager,
            router_manager=self.router_manager
        )
        
        manager.initialize()
        
        result = manager.setup_redirect(enabled=True)
        self.assertFalse(result)
    
    def test_enable_interactive(self):
        """Тест включения/выключения интерактивного режима."""
        manager = ConsoleManager(
            manager_name=self.manager_name,
            command_manager=self.command_manager,
            router_manager=self.router_manager,
            enabled=True
        )
        
        manager.initialize()
        
        # Включаем интерактивный режим
        result = manager.enable_interactive(enabled=True)
        self.assertTrue(result)
        self.assertTrue(manager.is_interactive())
        
        # Выключаем интерактивный режим
        result = manager.enable_interactive(enabled=False)
        self.assertTrue(result)
        self.assertFalse(manager.is_interactive())
    
    def test_enable_interactive_without_console(self):
        """Тест включения интерактивного режима без консоли."""
        manager = ConsoleManager(
            manager_name=self.manager_name,
            command_manager=self.command_manager,
            router_manager=self.router_manager
        )
        
        manager.initialize()
        
        result = manager.enable_interactive(enabled=True)
        self.assertFalse(result)
    
    def test_register_in_router(self):
        """Тест регистрации каналов в RouterManager."""
        router_manager = Mock()
        router_manager.register_channel = Mock(return_value=True)
        
        manager = ConsoleManager(
            manager_name=self.manager_name,
            command_manager=self.command_manager,
            router_manager=router_manager,
            enabled=True
        )
        
        manager.initialize()
        
        channels = manager.register_in_router(router_manager)
        
        self.assertGreater(len(channels), 0)
        router_manager.register_channel.assert_called()
    
    def test_get_output_queue(self):
        """Тест получения очереди вывода."""
        manager = ConsoleManager(
            manager_name=self.manager_name,
            command_manager=self.command_manager,
            router_manager=self.router_manager,
            enabled=True
        )
        
        manager.initialize()
        
        queue = manager.get_output_queue()
        self.assertIsNotNone(queue)
        # Используем hasattr вместо isinstance для совместимости с multiprocessing.Queue
        self.assertTrue(hasattr(queue, 'put') and hasattr(queue, 'get'))
    
    def test_get_input_queue(self):
        """Тест получения очереди ввода."""
        manager = ConsoleManager(
            manager_name=self.manager_name,
            command_manager=self.command_manager,
            router_manager=self.router_manager,
            enabled=True,
            interactive=True
        )
        
        manager.initialize()
        
        queue = manager.get_input_queue()
        self.assertIsNotNone(queue)
        # Используем hasattr вместо isinstance для совместимости с multiprocessing.Queue
        self.assertTrue(hasattr(queue, 'put') and hasattr(queue, 'get'))
    
    def test_format_message(self):
        """Тест форматирования сообщения."""
        manager = ConsoleManager(
            manager_name=self.manager_name,
            command_manager=self.command_manager,
            router_manager=self.router_manager
        )
        
        # Тест без временной метки
        formatted = manager._format_message("Test", "INFO", False)
        self.assertIn("Test", formatted)
        self.assertNotIn("[", formatted)  # Нет временной метки и уровня INFO
        
        # Тест с временной меткой
        formatted = manager._format_message("Test", "ERROR", True)
        self.assertIn("Test", formatted)
        self.assertIn("[ERROR]", formatted)
        self.assertIn("[", formatted)  # Есть временная метка
    
    def test_send_to_console(self):
        """Тест внутреннего метода отправки в консоль."""
        manager = ConsoleManager(
            manager_name=self.manager_name,
            command_manager=self.command_manager,
            router_manager=self.router_manager,
            enabled=True
        )
        
        manager.initialize()
        
        # Отправка в свою консоль
        result = manager._send_to_console("Test", self.manager_name)
        self.assertTrue(result)
        
        # Отправка без указания процесса
        result = manager._send_to_console("Test")
        self.assertTrue(result)


if __name__ == '__main__':
    unittest.main()

