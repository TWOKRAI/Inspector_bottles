"""
Тесты для работы с файлами в Config.

Проверяет:
- Загрузку из JSON файлов
- Загрузку из YAML файлов
- Сохранение в файлы
- Перезагрузку конфигурации
- Объединение при загрузке
"""
import pytest
import json
from pathlib import Path

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

from multiprocess_framework.modules.Config_module import Config


class TestConfigFileOperations:
    """Тесты для работы с файлами"""
    
    def test_load_json(self, config, temp_dir):
        """Тест загрузки из JSON файла"""
        # Создаем JSON файл
        json_data = {
            'database': {
                'host': 'localhost',
                'port': 5432
            },
            'api': {
                'port': 8000
            }
        }
        
        json_path = temp_dir / 'config.json'
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f)
        
        # Загружаем конфигурацию
        config.load(json_path)
        
        assert config.get('database.host') == 'localhost'
        assert config.get('database.port') == 5432
        assert config.get('api.port') == 8000
        assert config.file_path == json_path
    
    @pytest.mark.skipif(not YAML_AVAILABLE, reason="PyYAML не установлен")
    def test_load_yaml(self, config, temp_dir):
        """Тест загрузки из YAML файла"""
        yaml_content = """
database:
  host: localhost
  port: 5432
api:
  port: 8000
"""
        
        yaml_path = temp_dir / 'config.yaml'
        with open(yaml_path, 'w', encoding='utf-8') as f:
            f.write(yaml_content)
        
        # Загружаем конфигурацию
        config.load(yaml_path)
        
        assert config.get('database.host') == 'localhost'
        assert config.get('database.port') == 5432
        assert config.get('api.port') == 8000
        assert config.file_path == yaml_path
    
    def test_load_file_not_found(self, config, temp_dir):
        """Тест загрузки несуществующего файла"""
        nonexistent_path = temp_dir / 'nonexistent.json'
        
        with pytest.raises(FileNotFoundError):
            config.load(nonexistent_path)
    
    def test_save_json(self, config, temp_dir):
        """Тест сохранения в JSON файл"""
        # Устанавливаем значения
        config.set('database.host', 'localhost')
        config.set('database.port', 5432)
        config.set('api.port', 8000)
        
        # Сохраняем в файл
        json_path = temp_dir / 'config.json'
        config.save(json_path)
        
        # Проверяем что файл создан
        assert json_path.exists()
        
        # Загружаем обратно и проверяем
        new_config = Config()
        new_config.load(json_path)
        
        assert new_config.get('database.host') == 'localhost'
        assert new_config.get('database.port') == 5432
        assert new_config.get('api.port') == 8000
    
    @pytest.mark.skipif(not YAML_AVAILABLE, reason="PyYAML не установлен")
    def test_save_yaml(self, config, temp_dir):
        """Тест сохранения в YAML файл"""
        # Устанавливаем значения
        config.set('database.host', 'localhost')
        config.set('database.port', 5432)
        
        # Сохраняем в файл
        yaml_path = temp_dir / 'config.yaml'
        config.save(yaml_path)
        
        # Проверяем что файл создан
        assert yaml_path.exists()
        
        # Загружаем обратно и проверяем
        new_config = Config()
        new_config.load(yaml_path)
        
        assert new_config.get('database.host') == 'localhost'
        assert new_config.get('database.port') == 5432
    
    def test_save_without_path(self, config, temp_dir):
        """Тест сохранения без указания пути (использует путь загрузки)"""
        # Создаем и загружаем файл
        json_data = {'key': 'value'}
        json_path = temp_dir / 'config.json'
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f)
        
        config.load(json_path)
        
        # Изменяем значение
        config.set('key', 'new_value')
        
        # Сохраняем без указания пути
        config.save()
        
        # Проверяем что файл обновлен
        new_config = Config()
        new_config.load(json_path)
        assert new_config.get('key') == 'new_value'
    
    def test_save_without_load(self, config):
        """Тест сохранения без предварительной загрузки"""
        config.set('key', 'value')
        
        with pytest.raises(ValueError):
            config.save()
    
    def test_reload(self, config, temp_dir):
        """Тест перезагрузки конфигурации из файла"""
        # Создаем файл
        json_data = {'key': 'value1'}
        json_path = temp_dir / 'config.json'
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f)
        
        # Загружаем конфигурацию
        config.load(json_path)
        assert config.get('key') == 'value1'
        
        # Изменяем значение в конфиге
        config.set('key', 'value2')
        assert config.get('key') == 'value2'
        
        # Обновляем файл
        json_data['key'] = 'value3'
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f)
        
        # Перезагружаем конфигурацию
        config.reload()
        assert config.get('key') == 'value3'
    
    def test_reload_without_load(self, config):
        """Тест перезагрузки без предварительной загрузки"""
        with pytest.raises(ValueError):
            config.reload()
    
    def test_load_merge_true(self, config, temp_dir):
        """Тест загрузки с объединением (merge=True)"""
        # Устанавливаем начальные значения
        config.set('key1', 'value1')
        config.set('key2', 'value2')
        
        # Создаем файл с другими значениями
        json_data = {
            'key2': 'new_value2',
            'key3': 'value3'
        }
        json_path = temp_dir / 'config.json'
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f)
        
        # Загружаем с объединением
        config.load(json_path, merge=True)
        
        # Старые значения должны сохраниться
        assert config.get('key1') == 'value1'
        # Новые значения должны перезаписать старые
        assert config.get('key2') == 'new_value2'
        # Новые значения должны добавиться
        assert config.get('key3') == 'value3'
    
    def test_load_merge_false(self, config, temp_dir):
        """Тест загрузки с заменой (merge=False)"""
        # Устанавливаем начальные значения
        config.set('key1', 'value1')
        config.set('key2', 'value2')
        
        # Создаем файл с другими значениями
        json_data = {
            'key2': 'new_value2',
            'key3': 'value3'
        }
        json_path = temp_dir / 'config.json'
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f)
        
        # Загружаем с заменой
        config.load(json_path, merge=False)
        
        # Старые значения должны быть удалены
        assert config.get('key1') is None
        # Новые значения должны быть установлены
        assert config.get('key2') == 'new_value2'
        assert config.get('key3') == 'value3'
    
    def test_save_creates_directory(self, config, temp_dir):
        """Тест что сохранение создает директорию если её нет"""
        # Путь с несуществующей директорией
        json_path = temp_dir / 'subdir' / 'config.json'
        
        config.set('key', 'value')
        config.save(json_path)
        
        # Проверяем что файл создан
        assert json_path.exists()
        
        # Проверяем что директория создана
        assert json_path.parent.exists()
