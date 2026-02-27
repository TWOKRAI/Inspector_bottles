"""
Тесты для ProcessManagers.

Проверяют управление менеджерами процесса.
"""

import unittest
from multiprocess_framework.modules.Process_module.managers import ProcessManagers
from multiprocess_framework.modules.Process_module.config_handler import ProcessConfigHandler
from multiprocess_framework.modules.Process_manager_module.ProcessInteractionManager import ProcessInteractionManager


class TestProcessManagers(unittest.TestCase):
    """Тесты для ProcessManagers"""
    
    def setUp(self):
        """Подготовка тестового окружения"""
        self.process_name = "TestManagers"
        self.config = {
            'managers': {
                'logger': {
                    'app_name': 'TestApp'
                },
                'command': {
                    'enable_logging': True
                }
            }
        }
        self.config_handler = ProcessConfigHandler(
            process_name=self.process_name,
            config=self.config
        )
        self.interaction_manager = ProcessInteractionManager()
    
    def test_managers_initialization(self):
        """Тест инициализации менеджеров"""
        managers = ProcessManagers(
            process_name=self.process_name,
            config_handler=self.config_handler,
            interaction_manager=self.interaction_manager
        )
        
        # Проверяем, что реестры созданы
        self.assertIsNotNone(managers.managers)
        self.assertIsNotNone(managers.adapters)
    
    def test_initialize_core_managers(self):
        """Тест инициализации основных менеджеров"""
        managers = ProcessManagers(
            process_name=self.process_name,
            config_handler=self.config_handler,
            interaction_manager=self.interaction_manager
        )
        
        managers.initialize_core_managers()
        
        # Проверяем наличие основных менеджеров
        self.assertIsNotNone(managers.worker_manager)
        self.assertIsNotNone(managers.logger_manager)
        self.assertIsNotNone(managers.command_manager)
        self.assertIsNotNone(managers.router_manager)
        
        # Проверяем регистрацию
        self.assertIn("worker", managers.managers)
        self.assertIn("logger", managers.managers)
        self.assertIn("command", managers.managers)
        self.assertIn("router", managers.managers)
        
        # Проверяем адаптеры
        self.assertIn("logger", managers.adapters)
        self.assertIn("command", managers.adapters)
        self.assertIn("router", managers.adapters)
    
    def test_register_manager(self):
        """Тест регистрации менеджера"""
        managers = ProcessManagers(
            process_name=self.process_name,
            config_handler=self.config_handler,
            interaction_manager=self.interaction_manager
        )
        
        class MockManager:
            def __init__(self):
                self.name = "MockManager"
        
        mock_manager = MockManager()
        managers.register_manager("mock", mock_manager)
        
        self.assertIn("mock", managers.managers)
        self.assertEqual(managers.managers["mock"], mock_manager)
    
    def test_get_manager(self):
        """Тест получения менеджера"""
        managers = ProcessManagers(
            process_name=self.process_name,
            config_handler=self.config_handler,
            interaction_manager=self.interaction_manager
        )
        
        managers.initialize_core_managers()
        
        # Получаем существующий менеджер
        logger = managers.get_manager("logger")
        self.assertIsNotNone(logger)
        
        # Получаем несуществующий менеджер
        unknown = managers.get_manager("unknown")
        self.assertIsNone(unknown)
    
    def test_reload_manager(self):
        """Тест пересоздания менеджера"""
        managers = ProcessManagers(
            process_name=self.process_name,
            config_handler=self.config_handler,
            interaction_manager=self.interaction_manager
        )
        
        managers.initialize_core_managers()
        
        # Сохраняем старый менеджер
        old_logger = managers.logger_manager
        
        # Пересоздаем менеджер
        success = managers.reload_manager("logger")
        self.assertTrue(success)
        
        # Проверяем, что менеджер обновился
        self.assertIsNotNone(managers.logger_manager)
        # Новый менеджер должен быть другим объектом
        self.assertNotEqual(managers.logger_manager, old_logger)
    
    def test_reload_unsupported_manager(self):
        """Тест пересоздания неподдерживаемого менеджера"""
        managers = ProcessManagers(
            process_name=self.process_name,
            config_handler=self.config_handler,
            interaction_manager=self.interaction_manager
        )
        
        managers.initialize_core_managers()
        
        # Пытаемся пересоздать несуществующий менеджер
        success = managers.reload_manager("unknown")
        self.assertFalse(success)
    
    def test_get_stats(self):
        """Тест получения статистики"""
        managers = ProcessManagers(
            process_name=self.process_name,
            config_handler=self.config_handler,
            interaction_manager=self.interaction_manager
        )
        
        managers.initialize_core_managers()
        
        stats = managers.get_stats()
        
        # Проверяем структуру статистики
        self.assertIn("managers", stats)
        self.assertIn("adapters", stats)
        
        # Проверяем наличие статистики менеджеров
        self.assertIn("logger", stats["managers"])
        self.assertIn("command", stats["managers"])
        self.assertIn("router", stats["managers"])
    
    def test_stop_all(self):
        """Тест остановки всех менеджеров"""
        managers = ProcessManagers(
            process_name=self.process_name,
            config_handler=self.config_handler,
            interaction_manager=self.interaction_manager
        )
        
        managers.initialize_core_managers()
        
        # Останавливаем все (не должно вызывать ошибок)
        managers.stop_all()


if __name__ == '__main__':
    unittest.main()

