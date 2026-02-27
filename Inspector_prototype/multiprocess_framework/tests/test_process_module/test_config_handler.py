"""
Тесты для ProcessConfigHandler.

Проверяют работу с конфигурацией процесса.
"""

import unittest
from multiprocess_framework.modules.Process_module.config_handler import ProcessConfigHandler
from multiprocess_framework.modules.Config_module import ConfigManager


class TestProcessConfigHandler(unittest.TestCase):
    """Тесты для ProcessConfigHandler"""
    
    def setUp(self):
        """Подготовка тестового окружения"""
        self.process_name = "TestProcess"
        self.config = {
            'managers': {
                'logger': {
                    'app_name': 'TestApp'
                }
            }
        }
    
    def test_handler_initialization(self):
        """Тест инициализации обработчика конфигурации"""
        handler = ProcessConfigHandler(
            process_name=self.process_name,
            config=self.config
        )
        
        self.assertEqual(handler.process_name, self.process_name)
        self.assertEqual(handler.config, self.config)
    
    def test_get_managers_config_from_local(self):
        """Тест получения конфигурации менеджеров из локального config"""
        handler = ProcessConfigHandler(
            process_name=self.process_name,
            config=self.config
        )
        
        managers_config = handler.get_managers_config()
        self.assertIn('logger', managers_config)
        self.assertEqual(managers_config['logger']['app_name'], 'TestApp')
    
    def test_get_managers_config_from_config_manager(self):
        """Тест получения конфигурации менеджеров из ConfigManager"""
        config_manager = ConfigManager({
            'processes': {
                self.process_name: {
                    'managers': {
                        'logger': {
                            'app_name': 'ConfigApp'
                        }
                    }
                }
            }
        })
        
        handler = ProcessConfigHandler(
            process_name=self.process_name,
            config={},
            config_manager=config_manager
        )
        
        managers_config = handler.get_managers_config()
        self.assertIn('logger', managers_config)
        self.assertEqual(managers_config['logger']['app_name'], 'ConfigApp')
    
    def test_get_manager_config(self):
        """Тест получения конфигурации конкретного менеджера"""
        handler = ProcessConfigHandler(
            process_name=self.process_name,
            config=self.config
        )
        
        logger_config = handler.get_manager_config('logger')
        self.assertEqual(logger_config['app_name'], 'TestApp')
        
        # Несуществующий менеджер
        unknown_config = handler.get_manager_config('unknown')
        self.assertEqual(unknown_config, {})
    
    def test_update_config(self):
        """Тест обновления конфигурации"""
        handler = ProcessConfigHandler(
            process_name=self.process_name,
            config=self.config
        )
        
        new_config = {
            'managers': {
                'logger': {
                    'app_name': 'UpdatedApp'
                }
            }
        }
        
        success = handler.update_config(new_config)
        self.assertTrue(success)
        self.assertEqual(handler.config['managers']['logger']['app_name'], 'UpdatedApp')
    
    def test_update_config_with_config_manager(self):
        """Тест обновления конфигурации через ConfigManager"""
        config_manager = ConfigManager()
        
        handler = ProcessConfigHandler(
            process_name=self.process_name,
            config=self.config,
            config_manager=config_manager
        )
        
        new_config = {
            'managers': {
                'logger': {
                    'app_name': 'ConfigManagerApp'
                }
            }
        }
        
        success = handler.update_config(new_config)
        self.assertTrue(success)
        
        # Проверяем, что конфигурация обновилась в ConfigManager
        value = config_manager.get(f'processes.{self.process_name}.managers.logger.app_name')
        self.assertEqual(value, 'ConfigManagerApp')
    
    def test_get_config(self):
        """Тест получения значения конфигурации"""
        handler = ProcessConfigHandler(
            process_name=self.process_name,
            config={'test_key': 'test_value'}
        )
        
        value = handler.get_config('test_key')
        self.assertEqual(value, 'test_value')
        
        # Несуществующий ключ
        default_value = handler.get_config('unknown_key', 'default')
        self.assertEqual(default_value, 'default')
    
    def test_get_config_nested(self):
        """Тест получения вложенных значений конфигурации"""
        handler = ProcessConfigHandler(
            process_name=self.process_name,
            config={
                'nested': {
                    'key': 'value'
                }
            }
        )
        
        value = handler.get_config('nested.key')
        self.assertEqual(value, 'value')


if __name__ == '__main__':
    unittest.main()

