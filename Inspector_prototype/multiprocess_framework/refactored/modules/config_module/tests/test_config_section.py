"""
Тесты для класса ConfigSection.
"""
import unittest
import sys
from pathlib import Path

# Добавляем путь к модулю для абсолютных импортов
module_path = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(module_path))

from src.multiprocess_framework.refactored.modules.config_module.core.base_config import Config
from src.multiprocess_framework.refactored.modules.config_module.sections.config_section import ConfigSection


class TestConfigSection(unittest.TestCase):
    """Тесты для класса ConfigSection."""
    
    def setUp(self):
        """Подготовка к тестам."""
        self.config = Config()
        self.section = self.config.section('database')
    
    def test_get_set(self):
        """Тест получения и установки значений в секции."""
        self.section.set('host', 'localhost')
        self.assertEqual(self.section.get('host'), 'localhost')
        
        # Проверяем что изменения отражаются в основном конфиге
        self.assertEqual(self.config.get('database.host'), 'localhost')
    
    def test_update(self):
        """Тест обновления секции из словаря."""
        self.section.update({'host': 'localhost', 'port': 5432})
        
        self.assertEqual(self.section.get('host'), 'localhost')
        self.assertEqual(self.section.get('port'), 5432)
        self.assertEqual(self.config.get('database.host'), 'localhost')
        self.assertEqual(self.config.get('database.port'), 5432)
    
    def test_has(self):
        """Тест проверки наличия ключа в секции."""
        self.section.set('host', 'localhost')
        self.assertTrue(self.section.has('host'))
        self.assertFalse(self.section.has('port'))
    
    def test_remove(self):
        """Тест удаления ключа из секции."""
        self.section.set('host', 'localhost')
        self.assertTrue(self.section.remove('host'))
        self.assertFalse(self.section.has('host'))
        self.assertFalse(self.config.has('database.host'))
    
    def test_data_property(self):
        """Тест свойства data."""
        self.section.set('host', 'localhost')
        self.section.set('port', 5432)
        
        data = self.section.data
        self.assertEqual(data['host'], 'localhost')
        self.assertEqual(data['port'], 5432)
    
    def test_dict_syntax(self):
        """Тест синтаксиса словаря."""
        self.section['host'] = 'localhost'
        self.assertEqual(self.section['host'], 'localhost')
        self.assertTrue('host' in self.section)
        del self.section['host']
        self.assertFalse('host' in self.section)


if __name__ == '__main__':
    unittest.main()

