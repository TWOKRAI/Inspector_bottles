"""
Общие фикстуры для тестов Config_module.
"""
import pytest
import tempfile
import shutil
from pathlib import Path

from multiprocess_framework.modules.Config_module import Config, ConfigManager


@pytest.fixture(autouse=True)
def cleanup_config_manager():
    """
    Автоматическая очистка ConfigManager перед и после каждого теста.
    
    Эта фикстура гарантирует, что каждый тест начинается с чистого состояния.
    """
    # Очистка перед тестом
    ConfigManager.clear_all()
    yield
    # Очистка после теста
    ConfigManager.clear_all()


@pytest.fixture
def temp_dir():
    """
    Создает временную директорию для тестов.
    
    Yields:
        Path: Путь к временной директории
    """
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    # Очистка после теста
    if temp_path.exists():
        shutil.rmtree(temp_path)


@pytest.fixture
def config():
    """
    Создает пустой экземпляр Config для тестов.
    
    Returns:
        Config: Пустой экземпляр конфигурации
    """
    return Config()


@pytest.fixture
def config_with_data():
    """
    Создает экземпляр Config с начальными данными.
    
    Returns:
        Config: Экземпляр конфигурации с тестовыми данными
    """
    initial_data = {
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
    return Config(initial_data=initial_data)


@pytest.fixture
def json_config_file(temp_dir):
    """
    Создает временный JSON файл конфигурации.
    
    Args:
        temp_dir: Фикстура временной директории
        
    Returns:
        Path: Путь к созданному JSON файлу
    """
    import json
    
    config_data = {
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
        json.dump(config_data, f)
    
    return json_path


@pytest.fixture
def yaml_config_file(temp_dir):
    """
    Создает временный YAML файл конфигурации.
    
    Args:
        temp_dir: Фикстура временной директории
        
    Returns:
        Path: Путь к созданному YAML файлу
        
    Raises:
        pytest.skip: Если PyYAML не установлен
    """
    try:
        import yaml
    except ImportError:
        pytest.skip("PyYAML не установлен")
    
    config_data = {
        'database': {
            'host': 'localhost',
            'port': 5432
        },
        'api': {
            'port': 8000
        }
    }
    
    yaml_path = temp_dir / 'config.yaml'
    with open(yaml_path, 'w', encoding='utf-8') as f:
        yaml.dump(config_data, f)
    
    return yaml_path


@pytest.fixture
def config_dir(temp_dir):
    """
    Создает директорию для конфигурационных файлов.
    
    Args:
        temp_dir: Фикстура временной директории
        
    Returns:
        Path: Путь к директории конфигураций
    """
    config_path = temp_dir / 'config'
    config_path.mkdir(parents=True, exist_ok=True)
    return config_path


@pytest.fixture
def temp_config_dir(temp_dir):
    """
    Создает директорию для временных конфигурационных файлов.
    
    Args:
        temp_dir: Фикстура временной директории
        
    Returns:
        Path: Путь к директории временных конфигураций
    """
    temp_config_path = temp_dir / 'config' / 'temp'
    temp_config_path.mkdir(parents=True, exist_ok=True)
    return temp_config_path

