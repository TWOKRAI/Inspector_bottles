"""
Тесты для класса Config.
"""
import unittest
import sys
from pathlib import Path
import tempfile
import os
from pydantic import BaseModel, ValidationError

# Добавляем путь к модулю для абсолютных импортов
module_path = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(module_path))

from src.multiprocess_framework.refactored.modules.config_module.core.base_config import Config


class DatabaseConfig(BaseModel):
    """Тестовая схема для валидации."""
    host: str = "localhost"
    port: int = 5432
    name: str = "testdb"


class TestConfig(unittest.TestCase):
    """Тесты для класса Config."""
    
    def setUp(self):
        """Подготовка к тестам."""
        self.config = Config()
    
    def test_get_set(self):
        """Тест получения и установки значений."""
        self.config.set('key', 'value')
        self.assertEqual(self.config.get('key'), 'value')
    
    def test_nested_keys(self):
        """Тест вложенных ключей."""
        self.config.set('database.host', 'localhost')
        self.config.set('database.port', 5432)
        
        self.assertEqual(self.config.get('database.host'), 'localhost')
        self.assertEqual(self.config.get('database.port'), 5432)
    
    def test_default_value(self):
        """Тест значения по умолчанию."""
        value = self.config.get('nonexistent', 'default')
        self.assertEqual(value, 'default')
    
    def test_has(self):
        """Тест проверки наличия ключа."""
        self.config.set('key', 'value')
        self.assertTrue(self.config.has('key'))
        self.assertFalse(self.config.has('nonexistent'))
    
    def test_remove(self):
        """Тест удаления ключа."""
        self.config.set('key', 'value')
        self.assertTrue(self.config.remove('key'))
        self.assertFalse(self.config.has('key'))
    
    def test_clear(self):
        """Тест очистки конфигурации."""
        self.config.set('key1', 'value1')
        self.config.set('key2', 'value2')
        self.config.clear()
        self.assertEqual(len(self.config), 0)
    
    def test_update(self):
        """Тест обновления из словаря."""
        self.config.update({'key1': 'value1', 'key2': 'value2'})
        self.assertEqual(self.config.get('key1'), 'value1')
        self.assertEqual(self.config.get('key2'), 'value2')
    
    def test_load_save_json(self):
        """Тест загрузки и сохранения JSON."""
        # Создаем временный файл
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name
            f.write('{"key": "value"}')
        
        try:
            # Загружаем
            self.config.load(temp_path)
            self.assertEqual(self.config.get('key'), 'value')
            
            # Сохраняем
            self.config.set('key2', 'value2')
            self.config.save(temp_path)
            
            # Перезагружаем
            new_config = Config()
            new_config.load(temp_path)
            self.assertEqual(new_config.get('key'), 'value')
            self.assertEqual(new_config.get('key2'), 'value2')
        finally:
            os.unlink(temp_path)
    
    def test_load_save_yaml(self):
        """Тест загрузки и сохранения YAML."""
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        
        # Создаем временный файл
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            temp_path = f.name
            f.write('key: value\n')
        
        try:
            # Загружаем
            self.config.load(temp_path)
            self.assertEqual(self.config.get('key'), 'value')
            
            # Сохраняем
            self.config.set('key2', 'value2')
            self.config.save(temp_path)
            
            # Перезагружаем
            new_config = Config()
            new_config.load(temp_path)
            self.assertEqual(new_config.get('key'), 'value')
            self.assertEqual(new_config.get('key2'), 'value2')
        finally:
            os.unlink(temp_path)
    
    def test_validation_schema(self):
        """Тест валидации через Pydantic схему."""
        config = Config(validation_schema=DatabaseConfig, validate_on_set=False)
        
        # Устанавливаем значения
        config.set('host', 'localhost')
        config.set('port', 5432)
        config.set('name', 'testdb')
        
        # Конвертируем в модель
        model = config.to_model(DatabaseConfig)
        self.assertEqual(model.host, 'localhost')
        self.assertEqual(model.port, 5432)
        self.assertEqual(model.name, 'testdb')
    
    def test_from_model(self):
        """Тест загрузки из Pydantic модели."""
        model = DatabaseConfig(host='localhost', port=5432, name='testdb')
        config = Config()
        config.from_model(model)
        
        self.assertEqual(config.get('host'), 'localhost')
        self.assertEqual(config.get('port'), 5432)
        self.assertEqual(config.get('name'), 'testdb')
    
    def test_subscribe(self):
        """Тест подписки на изменения."""
        changes = []
        
        def callback(key, old_value, new_value):
            changes.append((key, old_value, new_value))
        
        self.config.subscribe(callback)
        self.config.set('key', 'value')
        
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0], ('key', None, 'value'))
    
    def test_dict_syntax(self):
        """Тест синтаксиса словаря."""
        self.config['key'] = 'value'
        self.assertEqual(self.config['key'], 'value')
        self.assertTrue('key' in self.config)
        del self.config['key']
        self.assertFalse('key' in self.config)
    
    def test_env_prefix(self):
        """Тест префикса переменных окружения."""
        import os
        os.environ['TEST_DATABASE_HOST'] = 'env_host'
        
        config = Config(env_prefix='TEST')
        value = config.get('database.host', env_fallback=True)
        
        # Очищаем переменную окружения
        del os.environ['TEST_DATABASE_HOST']
        
        self.assertEqual(value, 'env_host')


if __name__ == '__main__':
    unittest.main()

