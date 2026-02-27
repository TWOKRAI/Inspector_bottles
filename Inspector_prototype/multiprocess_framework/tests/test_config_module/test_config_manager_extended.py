"""
Расширенные тесты для ConfigManager.

Проверяет новую функциональность:
- Загрузка конфигов с дефолтными и временными файлами
- Автоматическое определение класса конфига
- Загрузка всех конфигов из директории
- Сброс к дефолтным значениям
- Сохранение во временный файл
"""
import pytest
import yaml
import json
from pathlib import Path

from multiprocess_framework.modules.Config_module import ConfigManager, Config

# Пытаемся импортировать ProcessConfig, но не падаем если его нет
try:
    from multiprocess_framework.modules.Process_manager_module.process_config import ProcessConfig
    PROCESS_CONFIG_AVAILABLE = True
except ImportError:
    PROCESS_CONFIG_AVAILABLE = False


class TestConfigManagerExtended:
    """Расширенные тесты для ConfigManager"""
    
    def test_load_config_with_default_path(self, config_dir):
        """Тест загрузки конфига с дефолтным файлом"""
        # Создаем дефолтный файл
        default_file = config_dir / 'test.yaml'
        with open(default_file, 'w', encoding='utf-8') as f:
            yaml.dump({'key': 'default_value'}, f)
        
        config = ConfigManager.load_config(
            name='test',
            default_path=str(default_file)
        )
        
        assert config.get('key') == 'default_value'
        assert ConfigManager.get_default_path('test') == default_file
    
    def test_load_config_with_temp_path(self, config_dir, temp_config_dir):
        """Тест загрузки конфига с временным файлом (приоритет над дефолтным)"""
        # Создаем дефолтный файл
        default_file = config_dir / 'test.yaml'
        with open(default_file, 'w', encoding='utf-8') as f:
            yaml.dump({'key': 'default_value'}, f)
        
        # Создаем временный файл
        temp_file = temp_config_dir / 'test.yaml'
        with open(temp_file, 'w', encoding='utf-8') as f:
            yaml.dump({'key': 'temp_value'}, f)
        
        config = ConfigManager.load_config(
            name='test',
            default_path=str(default_file),
            temp_path=str(temp_file)
        )
        
        # Временный файл должен иметь приоритет
        assert config.get('key') == 'temp_value'
    
    @pytest.mark.skipif(not PROCESS_CONFIG_AVAILABLE, reason="ProcessConfig не доступен")
    def test_load_config_with_config_class(self):
        """Тест загрузки конфига с указанием класса"""
        config = ConfigManager.load_config(
            name='processes',
            config_class='src.Modules.Process_manager_module.process_config.ProcessConfig'
        )
        
        assert isinstance(config, ProcessConfig)
        assert hasattr(config, 'add_process_config')
        assert hasattr(config, 'get_enabled_configs')
    
    @pytest.mark.skipif(not PROCESS_CONFIG_AVAILABLE, reason="ProcessConfig не доступен")
    def test_load_config_with_meta_class(self, config_dir):
        """Тест автоматического определения класса из метаданных"""
        # Создаем файл с метаданными
        config_file = config_dir / 'processes.yaml'
        with open(config_file, 'w', encoding='utf-8') as f:
            yaml.dump({
                '_meta': {
                    'config_class': 'src.Modules.Process_manager_module.process_config.ProcessConfig'
                },
                'test': 'value'
            }, f)
        
        config = ConfigManager.load_config(
            name='processes',
            default_path=str(config_file)
        )
        
        # Класс должен быть автоматически определен из метаданных
        assert config is not None
        assert isinstance(config, ProcessConfig)
        assert hasattr(config, 'add_process_config')
        assert hasattr(config, 'get_enabled_configs')
    
    def test_load_all_configs(self, config_dir):
        """Тест загрузки всех конфигов из директории"""
        # Создаем несколько конфигов
        config1_file = config_dir / 'app.yaml'
        config2_file = config_dir / 'database.yaml'
        
        with open(config1_file, 'w', encoding='utf-8') as f:
            yaml.dump({'app_name': 'MyApp'}, f)
        
        with open(config2_file, 'w', encoding='utf-8') as f:
            yaml.dump({'host': 'localhost'}, f)
        
        configs = ConfigManager.load_all_configs(config_dir=str(config_dir))
        
        assert 'app' in configs
        assert 'database' in configs
        assert configs['app'].get('app_name') == 'MyApp'
        assert configs['database'].get('host') == 'localhost'
    
    @pytest.mark.skipif(not PROCESS_CONFIG_AVAILABLE, reason="ProcessConfig не доступен")
    def test_load_all_configs_with_mapping(self, config_dir):
        """Тест загрузки конфигов с маппингом"""
        # Создаем конфиг
        config_file = config_dir / 'processes.yaml'
        with open(config_file, 'w', encoding='utf-8') as f:
            yaml.dump({'test': 'value'}, f)
        
        configs = ConfigManager.load_all_configs(
            config_dir=str(config_dir),
            config_mapping={
                'processes': {
                    'default_path': str(config_file),
                    'config_class': 'src.Modules.Process_manager_module.process_config.ProcessConfig'
                }
            }
        )
        
        assert 'processes' in configs
        assert isinstance(configs['processes'], ProcessConfig)
    
    def test_reset_to_default(self, config_dir, temp_config_dir):
        """Тест сброса конфига к дефолтным значениям"""
        # Создаем дефолтный файл
        default_file = config_dir / 'test.yaml'
        with open(default_file, 'w', encoding='utf-8') as f:
            yaml.dump({'key': 'default_value'}, f)
        
        # Создаем временный файл с другими значениями
        temp_file = temp_config_dir / 'test.yaml'
        with open(temp_file, 'w', encoding='utf-8') as f:
            yaml.dump({'key': 'temp_value'}, f)
        
        # Загружаем конфиг
        config = ConfigManager.load_config(
            name='test',
            default_path=str(default_file),
            temp_path=str(temp_file)
        )
        
        # Проверяем что загружен временный
        assert config.get('key') == 'temp_value'
        
        # Изменяем значение
        config.set('key', 'modified_value')
        
        # Сбрасываем к дефолту
        success = ConfigManager.reset_to_default('test')
        assert success is True
        
        # Проверяем что значение сброшено
        assert config.get('key') == 'default_value'
    
    def test_save_temp(self, config_dir, temp_config_dir):
        """Тест сохранения конфига во временный файл"""
        # Создаем дефолтный файл
        default_file = config_dir / 'test.yaml'
        with open(default_file, 'w', encoding='utf-8') as f:
            yaml.dump({'key': 'default_value'}, f)
        
        # Загружаем конфиг
        config = ConfigManager.load_config(
            name='test',
            default_path=str(default_file),
            temp_path=str(temp_config_dir / 'test.yaml')
        )
        
        # Изменяем значение
        config.set('key', 'new_value')
        
        # Сохраняем во временный файл
        success = ConfigManager.save_temp('test')
        assert success is True
        
        # Проверяем что файл сохранен
        temp_file = temp_config_dir / 'test.yaml'
        assert temp_file.exists()
        
        # Проверяем содержимое
        with open(temp_file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            assert data['key'] == 'new_value'
    
    def test_get_default_path(self, config_dir):
        """Тест получения пути к дефолтному файлу"""
        default_file = config_dir / 'test.yaml'
        
        ConfigManager.load_config(
            name='test',
            default_path=str(default_file)
        )
        
        assert ConfigManager.get_default_path('test') == default_file
        assert ConfigManager.get_default_path('nonexistent') is None
    
    def test_get_temp_path(self, temp_config_dir):
        """Тест получения пути к временному файлу"""
        temp_file = temp_config_dir / 'test.yaml'
        
        ConfigManager.load_config(
            name='test',
            temp_path=str(temp_file)
        )
        
        assert ConfigManager.get_temp_path('test') == temp_file
        assert ConfigManager.get_temp_path('nonexistent') is None
    
    def test_load_config_invalid_class(self):
        """Тест загрузки конфига с неверным классом (должен использовать базовый Config)"""
        config = ConfigManager.load_config(
            name='test',
            config_class='nonexistent.module.NonExistentClass'
        )
        
        # Должен использовать базовый Config при ошибке
        assert isinstance(config, Config)
        if PROCESS_CONFIG_AVAILABLE:
            assert not isinstance(config, ProcessConfig)
    
    def test_load_config_nonexistent_files(self):
        """Тест загрузки конфига с несуществующими файлами"""
        config = ConfigManager.load_config(
            name='test',
            default_path='nonexistent/path.yaml',
            temp_path='nonexistent/temp.yaml'
        )
        
        # Должен создать пустой конфиг
        assert config is not None
        assert len(config.data) == 0
