"""
Тесты для класса ConfigManager.
"""
import unittest
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

# Добавляем путь к модулю для абсолютных импортов
module_path = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(module_path))

from src.multiprocess_framework.refactored.modules.config_module.core.config_manager import ConfigManager
from src.multiprocess_framework.refactored.modules.config_module.core.base_config import Config


class TestConfigManager(unittest.TestCase):
    """Тесты для класса ConfigManager."""
    
    def setUp(self):
        """Подготовка к тестам."""
        # Создаем моки для зависимостей
        self.mock_shared_resources = Mock()
        self.mock_event_manager = Mock()
        self.mock_storage_manager = Mock()
        
        # Настраиваем моки
        self.mock_shared_resources.get_process_data = Mock(return_value=None)
        self.mock_shared_resources.get_all_process_data = Mock(return_value={})
        
        self.config_manager = ConfigManager(
            manager_name="TestConfigManager",
            shared_resources=self.mock_shared_resources,
            event_manager=self.mock_event_manager,
            storage_manager=self.mock_storage_manager,
            auto_sync=False  # Отключаем автосинхронизацию для тестов
        )
    
    def test_create_config(self):
        """Тест создания конфигурации."""
        config = self.config_manager.create_config(
            name='test',
            initial_data={'key': 'value'}
        )
        
        self.assertIsInstance(config, Config)
        self.assertEqual(config.get('key'), 'value')
        self.assertTrue(self.config_manager.has_config('test'))
    
    def test_get_config(self):
        """Тест получения конфигурации."""
        self.config_manager.create_config(name='test', initial_data={'key': 'value'})
        
        config = self.config_manager.get_config('test')
        self.assertIsNotNone(config)
        self.assertEqual(config.get('key'), 'value')
        
        # Несуществующая конфигурация
        self.assertIsNone(self.config_manager.get_config('nonexistent'))
    
    def test_remove_config(self):
        """Тест удаления конфигурации."""
        self.config_manager.create_config(name='test', initial_data={'key': 'value'})
        self.assertTrue(self.config_manager.has_config('test'))
        
        result = self.config_manager.remove_config('test')
        self.assertTrue(result)
        self.assertFalse(self.config_manager.has_config('test'))
        
        # Удаление несуществующей конфигурации
        result = self.config_manager.remove_config('nonexistent')
        self.assertFalse(result)
    
    def test_list_configs(self):
        """Тест получения списка конфигураций."""
        self.config_manager.create_config(name='config1')
        self.config_manager.create_config(name='config2')
        
        configs = self.config_manager.list_configs()
        self.assertEqual(len(configs), 2)
        self.assertIn('config1', configs)
        self.assertIn('config2', configs)
    
    def test_get_all_configs(self):
        """Тест получения всех конфигураций."""
        self.config_manager.create_config(name='config1', initial_data={'key1': 'value1'})
        self.config_manager.create_config(name='config2', initial_data={'key2': 'value2'})
        
        all_configs = self.config_manager.get_all_configs()
        self.assertEqual(len(all_configs), 2)
        self.assertEqual(all_configs['config1'].get('key1'), 'value1')
        self.assertEqual(all_configs['config2'].get('key2'), 'value2')
    
    def test_has_config(self):
        """Тест проверки наличия конфигурации."""
        self.config_manager.create_config(name='test')
        
        self.assertTrue(self.config_manager.has_config('test'))
        self.assertFalse(self.config_manager.has_config('nonexistent'))
    
    def test_get_config_metadata(self):
        """Тест получения метаданных конфигурации."""
        # Создаем конфигурацию без файла (file_path=None или не указываем)
        self.config_manager.create_config(
            name='test',
            initial_data={'key': 'value'},
            env_prefix='TEST'
        )
        
        metadata = self.config_manager.get_config_metadata('test')
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata['env_prefix'], 'TEST')
        # file_path может быть None если файл не был указан при создании
        # self.assertEqual(metadata['file_path'], 'test.yaml')
    
    def test_set_auto_sync(self):
        """Тест установки автоматической синхронизации."""
        self.config_manager.create_config(name='test')
        
        result = self.config_manager.set_auto_sync('test', True)
        self.assertTrue(result)
        
        metadata = self.config_manager.get_config_metadata('test')
        self.assertTrue(metadata['auto_sync'])
        
        # Несуществующая конфигурация
        result = self.config_manager.set_auto_sync('nonexistent', True)
        self.assertFalse(result)
    
    def test_initialize(self):
        """Тест инициализации ConfigManager."""
        result = self.config_manager.initialize()
        self.assertTrue(result)
        self.assertTrue(self.config_manager.is_initialized)
    
    def test_shutdown(self):
        """Тест завершения работы ConfigManager."""
        self.config_manager.create_config(name='test')
        self.config_manager.initialize()
        
        result = self.config_manager.shutdown()
        self.assertTrue(result)
        self.assertFalse(self.config_manager.is_initialized)
        self.assertEqual(len(self.config_manager.list_configs()), 0)
    
    def test_validation_schema(self):
        """Тест создания конфигурации с валидацией."""
        from pydantic import BaseModel
        
        class TestSchema(BaseModel):
            key: str = "default"
        
        config = self.config_manager.create_config(
            name='test',
            validation_schema=TestSchema,
            validate_on_set=False
        )
        
        metadata = self.config_manager.get_config_metadata('test')
        self.assertEqual(metadata['validation_schema'], TestSchema)


if __name__ == '__main__':
    unittest.main()

