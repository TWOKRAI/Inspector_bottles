"""
Тесты для ProcessConfig.

Проверяют работу с конфигурацией процессов.
"""

import unittest
from multiprocess_framework.modules.Process_manager_module.config import ProcessConfig


class MockProcess:
    """Мок-класс процесса для тестирования"""
    pass


class TestProcessConfig(unittest.TestCase):
    """Тесты для ProcessConfig"""
    
    def setUp(self):
        """Подготовка тестового окружения"""
        self.config = ProcessConfig()
    
    def test_add_process_config(self):
        """Тест добавления конфигурации процесса"""
        self.config.add_process_config(
            name="TestProcess",
            process_class=MockProcess,
            priority="high",
            config={"test": "value"},
            enabled=True
        )
        
        config = self.config.get_process_config("TestProcess")
        self.assertIsNotNone(config)
        self.assertEqual(config['class'], MockProcess)
        self.assertEqual(config['priority'], "high")
        self.assertEqual(config['config']['test'], "value")
        self.assertTrue(config['enabled'])
    
    def test_get_enabled_configs(self):
        """Тест получения только включенных конфигураций"""
        self.config.add_process_config("Process1", MockProcess, enabled=True)
        self.config.add_process_config("Process2", MockProcess, enabled=False)
        
        enabled = self.config.get_enabled_configs()
        self.assertEqual(len(enabled), 1)
        self.assertIn("Process1", enabled)
        self.assertNotIn("Process2", enabled)
    
    def test_process_configs_property(self):
        """Тест свойства process_configs для обратной совместимости"""
        self.config.add_process_config("Process1", MockProcess)
        self.config.add_process_config("Process2", MockProcess)
        
        all_configs = self.config.process_configs
        self.assertEqual(len(all_configs), 2)
        self.assertIn("Process1", all_configs)
        self.assertIn("Process2", all_configs)
    
    def test_update_config_via_set(self):
        """Тест обновления конфигурации через set"""
        self.config.add_process_config("TestProcess", MockProcess, priority="normal")
        
        # Обновляем через set (базовый метод Config)
        config_data = self.config.get_process_config("TestProcess")
        config_data['priority'] = 'high'
        self.config.set("TestProcess", config_data)
        
        updated_config = self.config.get_process_config("TestProcess")
        self.assertEqual(updated_config['priority'], "high")
    
    def test_remove_config_via_remove(self):
        """Тест удаления конфигурации через remove"""
        self.config.add_process_config("TestProcess", MockProcess)
        
        # Удаляем через remove (базовый метод Config)
        success = self.config.remove("TestProcess")
        self.assertTrue(success)
        
        config = self.config.get_process_config("TestProcess")
        self.assertIsNone(config)
    
    def test_validate_config_valid(self):
        """Тест валидации корректной конфигурации"""
        config = {
            'class': MockProcess,
            'priority': 'normal',
            'config': {}
        }
        
        is_valid, error = self.config.validate_config(config)
        self.assertTrue(is_valid)
        self.assertIsNone(error)
    
    def test_validate_config_missing_class(self):
        """Тест валидации конфигурации без класса"""
        config = {
            'priority': 'normal'
        }
        
        is_valid, error = self.config.validate_config(config)
        self.assertFalse(is_valid)
        self.assertIsNotNone(error)
    
    def test_validate_config_invalid_priority(self):
        """Тест валидации конфигурации с невалидным приоритетом"""
        config = {
            'class': MockProcess,
            'priority': 'invalid_priority'
        }
        
        is_valid, error = self.config.validate_config(config)
        self.assertFalse(is_valid)
        self.assertIsNotNone(error)
    
    def test_load_from_dict(self):
        """Тест загрузки конфигураций из словаря"""
        process_config = {
            'Process1': {
                'class': MockProcess,
                'priority': 'high',
                'enabled': True,
                'config': {'test': 'value'}
            },
            'Process2': {
                'class': MockProcess,
                'priority': 'normal',
                'enabled': False
            }
        }
        
        self.config.load_from_dict(process_config)
        
        config1 = self.config.get_process_config("Process1")
        self.assertIsNotNone(config1)
        self.assertEqual(config1['priority'], 'high')
        
        config2 = self.config.get_process_config("Process2")
        self.assertIsNotNone(config2)
        self.assertFalse(config2['enabled'])


if __name__ == '__main__':
    unittest.main()

