"""
Расширенные тесты для чтения конфигураций из JSON и YAML файлов.

Проверяет:
- Чтение различных типов данных из файлов
- Чтение сложных вложенных структур
- Чтение конфигураций через ConfigManager
- Обработку различных форматов файлов
- Чтение конфигураций с различными кодировками
"""
import pytest
import json
from pathlib import Path

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

from multiprocess_framework.modules.Config_module import Config, ConfigManager


class TestConfigFileReading:
    """Расширенные тесты для чтения конфигураций из файлов"""
    
    def test_read_json_complex_structure(self, temp_dir):
        """Тест чтения сложной структуры из JSON файла"""
        json_data = {
            'app': {
                'name': 'MyApp',
                'version': '1.0.0',
                'debug': True
            },
            'database': {
                'host': 'localhost',
                'port': 5432,
                'credentials': {
                    'user': 'admin',
                    'password': 'secret'
                },
                'options': {
                    'pool_size': 10,
                    'timeout': 30.5
                }
            },
            'api': {
                'endpoints': ['/api/v1', '/api/v2'],
                'rate_limit': 100,
                'cors': {
                    'allowed_origins': ['http://localhost:3000', 'https://example.com'],
                    'enabled': True
                }
            },
            'features': {
                'enabled': ['feature1', 'feature2'],
                'disabled': []
            }
        }
        
        json_path = temp_dir / 'config.json'
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, indent=2)
        
        config = Config()
        config.load(json_path)
        
        # Проверяем простые значения
        assert config.get('app.name') == 'MyApp'
        assert config.get('app.version') == '1.0.0'
        assert config.get('app.debug') is True
        
        # Проверяем вложенные значения
        assert config.get('database.host') == 'localhost'
        assert config.get('database.port') == 5432
        assert config.get('database.credentials.user') == 'admin'
        assert config.get('database.credentials.password') == 'secret'
        
        # Проверяем числовые значения
        assert config.get('database.options.pool_size') == 10
        assert config.get('database.options.timeout') == 30.5
        
        # Проверяем списки
        endpoints = config.get('api.endpoints')
        assert isinstance(endpoints, list)
        assert '/api/v1' in endpoints
        assert '/api/v2' in endpoints
        
        # Проверяем вложенные структуры
        assert config.get('api.cors.enabled') is True
        assert 'http://localhost:3000' in config.get('api.cors.allowed_origins')
    
    @pytest.mark.skipif(not YAML_AVAILABLE, reason="PyYAML не установлен")
    def test_read_yaml_complex_structure(self, temp_dir):
        """Тест чтения сложной структуры из YAML файла"""
        yaml_content = """
app:
  name: MyApp
  version: 1.0.0
  debug: true

database:
  host: localhost
  port: 5432
  credentials:
    user: admin
    password: secret
  options:
    pool_size: 10
    timeout: 30.5

api:
  endpoints:
    - /api/v1
    - /api/v2
  rate_limit: 100
  cors:
    allowed_origins:
      - http://localhost:3000
      - https://example.com
    enabled: true

features:
  enabled:
    - feature1
    - feature2
  disabled: []
"""
        
        yaml_path = temp_dir / 'config.yaml'
        with open(yaml_path, 'w', encoding='utf-8') as f:
            f.write(yaml_content)
        
        config = Config()
        config.load(yaml_path)
        
        # Проверяем простые значения
        assert config.get('app.name') == 'MyApp'
        assert config.get('app.version') == '1.0.0'
        assert config.get('app.debug') is True
        
        # Проверяем вложенные значения
        assert config.get('database.host') == 'localhost'
        assert config.get('database.port') == 5432
        assert config.get('database.credentials.user') == 'admin'
        
        # Проверяем числовые значения
        assert config.get('database.options.pool_size') == 10
        assert config.get('database.options.timeout') == 30.5
        
        # Проверяем списки
        endpoints = config.get('api.endpoints')
        assert isinstance(endpoints, list)
        assert '/api/v1' in endpoints
    
    def test_read_json_with_all_data_types(self, temp_dir):
        """Тест чтения JSON файла со всеми типами данных"""
        json_data = {
            'string_value': 'text',
            'int_value': 42,
            'float_value': 3.14,
            'bool_true': True,
            'bool_false': False,
            'null_value': None,
            'list_value': [1, 2, 3],
            'dict_value': {
                'nested': 'value'
            },
            'empty_list': [],
            'empty_dict': {}
        }
        
        json_path = temp_dir / 'types.json'
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f)
        
        config = Config()
        config.load(json_path)
        
        assert config.get('string_value') == 'text'
        assert config.get('int_value') == 42
        assert config.get('float_value') == 3.14
        assert config.get('bool_true') is True
        assert config.get('bool_false') is False
        assert config.get('null_value') is None
        assert config.get('list_value') == [1, 2, 3]
        assert config.get('dict_value.nested') == 'value'
        assert config.get('empty_list') == []
        assert config.get('empty_dict') == {}
    
    @pytest.mark.skipif(not YAML_AVAILABLE, reason="PyYAML не установлен")
    def test_read_yaml_with_all_data_types(self, temp_dir):
        """Тест чтения YAML файла со всеми типами данных"""
        yaml_content = """
string_value: text
int_value: 42
float_value: 3.14
bool_true: true
bool_false: false
null_value: null
list_value:
  - 1
  - 2
  - 3
dict_value:
  nested: value
empty_list: []
empty_dict: {}
"""
        
        yaml_path = temp_dir / 'types.yaml'
        with open(yaml_path, 'w', encoding='utf-8') as f:
            f.write(yaml_content)
        
        config = Config()
        config.load(yaml_path)
        
        assert config.get('string_value') == 'text'
        assert config.get('int_value') == 42
        assert config.get('float_value') == 3.14
        assert config.get('bool_true') is True
        assert config.get('bool_false') is False
        assert config.get('null_value') is None
        assert config.get('list_value') == [1, 2, 3]
        assert config.get('dict_value.nested') == 'value'
    
    def test_read_json_via_config_manager(self, temp_dir):
        """Тест чтения JSON конфигурации через ConfigManager"""
        json_data = {
            'database': {
                'host': 'localhost',
                'port': 5432
            }
        }
        
        json_path = temp_dir / 'app.json'
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f)
        
        # Создаем конфигурацию через ConfigManager с автоматической загрузкой
        config = ConfigManager.get_instance('app', file_path=str(json_path))
        
        assert config.get('database.host') == 'localhost'
        assert config.get('database.port') == 5432
        
        # Проверяем что это тот же экземпляр
        config2 = ConfigManager.get_instance('app')
        assert config is config2
    
    @pytest.mark.skipif(not YAML_AVAILABLE, reason="PyYAML не установлен")
    def test_read_yaml_via_config_manager(self, temp_dir):
        """Тест чтения YAML конфигурации через ConfigManager"""
        yaml_content = """
database:
  host: localhost
  port: 5432
"""
        
        yaml_path = temp_dir / 'app.yaml'
        with open(yaml_path, 'w', encoding='utf-8') as f:
            f.write(yaml_content)
        
        # Создаем конфигурацию через ConfigManager
        config = ConfigManager.get_instance('app', file_path=str(yaml_path))
        
        assert config.get('database.host') == 'localhost'
        assert config.get('database.port') == 5432
    
    def test_read_json_with_unicode(self, temp_dir):
        """Тест чтения JSON файла с Unicode символами"""
        json_data = {
            'app': {
                'name': 'МоеПриложение',
                'description': 'Описание приложения с русскими символами',
                'author': 'Автор © 2024'
            }
        }
        
        json_path = temp_dir / 'unicode.json'
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False)
        
        config = Config()
        config.load(json_path)
        
        assert config.get('app.name') == 'МоеПриложение'
        assert config.get('app.description') == 'Описание приложения с русскими символами'
        assert config.get('app.author') == 'Автор © 2024'
    
    @pytest.mark.skipif(not YAML_AVAILABLE, reason="PyYAML не установлен")
    def test_read_yaml_with_unicode(self, temp_dir):
        """Тест чтения YAML файла с Unicode символами"""
        yaml_content = """
app:
  name: МоеПриложение
  description: Описание приложения с русскими символами
  author: Автор © 2024
"""
        
        yaml_path = temp_dir / 'unicode.yaml'
        with open(yaml_path, 'w', encoding='utf-8') as f:
            f.write(yaml_content)
        
        config = Config()
        config.load(yaml_path)
        
        assert config.get('app.name') == 'МоеПриложение'
        assert config.get('app.description') == 'Описание приложения с русскими символами'
    
    def test_read_json_with_sections(self, temp_dir):
        """Тест чтения JSON и работы с секциями"""
        json_data = {
            'database': {
                'host': 'localhost',
                'port': 5432,
                'name': 'mydb'
            },
            'api': {
                'port': 8000,
                'host': '0.0.0.0'
            }
        }
        
        json_path = temp_dir / 'config.json'
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f)
        
        config = Config()
        config.load(json_path)
        
        # Работаем с секциями
        db_section = config.section('database')
        assert db_section.get('host') == 'localhost'
        assert db_section.get('port') == 5432
        
        api_section = config.section('api')
        assert api_section.get('port') == 8000
        assert api_section.get('host') == '0.0.0.0'
