"""
Тесты для ConfigManager.

Проверяет:
- Singleton паттерн
- Создание именованных конфигураций
- Управление несколькими конфигурациями
- Удаление конфигураций
"""
import pytest
import json
from pathlib import Path

from multiprocess_framework.modules.Config_module import ConfigManager, get_config


class TestConfigManager:
    """Тесты для ConfigManager"""
    
    def test_get_instance_default(self):
        """Тест получения дефолтного экземпляра"""
        config1 = ConfigManager.get_instance()
        config2 = ConfigManager.get_instance()
        
        # Должен быть один и тот же экземпляр
        assert config1 is config2
    
    def test_get_instance_named(self):
        """Тест получения именованного экземпляра"""
        config1 = ConfigManager.get_instance('app')
        config2 = ConfigManager.get_instance('app')
        
        # Должен быть один и тот же экземпляр
        assert config1 is config2
        
        # Разные имена - разные экземпляры
        config3 = ConfigManager.get_instance('database')
        assert config1 is not config3
    
    def test_get_instance_with_env_prefix(self):
        """Тест создания экземпляра с префиксом для переменных окружения"""
        config = ConfigManager.get_instance('app', env_prefix='APP')
        
        assert config._env_prefix == 'APP'
    
    def test_get_instance_with_file_path(self, temp_dir):
        """Тест создания экземпляра с автоматической загрузкой из файла"""
        # Создаем временный файл
        json_path = temp_dir / 'config.json'
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump({'key': 'value'}, f)
        
        config = ConfigManager.get_instance('app', file_path=str(json_path))
        
        assert config.get('key') == 'value'
        assert config.file_path == json_path
    
    def test_create_instance(self):
        """Тест создания нового экземпляра"""
        config1 = ConfigManager.create_instance('new_config')
        config1.set('key', 'value1')
        
        # Создаем новый экземпляр с тем же именем
        config2 = ConfigManager.create_instance('new_config')
        
        # Это должен быть новый экземпляр
        assert config1 is not config2
        # Старые данные должны быть потеряны
        assert config2.get('key') is None
    
    def test_create_instance_with_data(self):
        """Тест создания экземпляра с начальными данными"""
        initial_data = {'database': {'host': 'localhost'}}
        config = ConfigManager.create_instance('app', initial_data=initial_data)
        
        assert config.get('database.host') == 'localhost'
    
    def test_remove_instance(self):
        """Тест удаления экземпляра"""
        config = ConfigManager.get_instance('app')
        config.set('key', 'value')
        
        # Удаляем экземпляр
        assert ConfigManager.remove_instance('app') is True
        
        # Проверяем что экземпляр удален
        assert ConfigManager.has_instance('app') is False
        
        # Создаем новый экземпляр с тем же именем
        new_config = ConfigManager.get_instance('app')
        assert config is not new_config
        assert new_config.get('key') is None
    
    def test_remove_nonexistent_instance(self):
        """Тест удаления несуществующего экземпляра"""
        assert ConfigManager.remove_instance('nonexistent') is False
    
    def test_clear_all(self):
        """Тест очистки всех экземпляров"""
        ConfigManager.get_instance('app')
        ConfigManager.get_instance('database')
        ConfigManager.get_instance('api')
        
        assert len(ConfigManager.list_instances()) == 3
        
        ConfigManager.clear_all()
        
        assert len(ConfigManager.list_instances()) == 0
    
    def test_has_instance(self):
        """Тест проверки существования экземпляра"""
        assert ConfigManager.has_instance('app') is False
        
        ConfigManager.get_instance('app')
        
        assert ConfigManager.has_instance('app') is True
        assert ConfigManager.has_instance('nonexistent') is False
    
    def test_list_instances(self):
        """Тест получения списка экземпляров"""
        assert ConfigManager.list_instances() == []
        
        ConfigManager.get_instance('app')
        ConfigManager.get_instance('database')
        ConfigManager.get_instance('api')
        
        instances = ConfigManager.list_instances()
        assert len(instances) == 3
        assert 'app' in instances
        assert 'database' in instances
        assert 'api' in instances
    
    def test_get_all_instances(self):
        """Тест получения всех экземпляров"""
        config1 = ConfigManager.get_instance('app')
        config2 = ConfigManager.get_instance('database')
        
        all_instances = ConfigManager.get_all_instances()
        
        assert len(all_instances) == 2
        assert 'app' in all_instances
        assert 'database' in all_instances
        assert all_instances['app'] is config1
        assert all_instances['database'] is config2
    
    def test_multiple_instances_independent(self):
        """Тест что разные экземпляры независимы"""
        app_config = ConfigManager.get_instance('app')
        db_config = ConfigManager.get_instance('database')
        
        app_config.set('key', 'app_value')
        db_config.set('key', 'db_value')
        
        assert app_config.get('key') == 'app_value'
        assert db_config.get('key') == 'db_value'
    
    def test_get_config_function(self):
        """Тест функции get_config"""
        config1 = get_config('app')
        config2 = get_config('app')
        
        # Должен быть один и тот же экземпляр
        assert config1 is config2
        
        # Разные имена - разные экземпляры
        config3 = get_config('database')
        assert config1 is not config3
    
    def test_get_config_default(self):
        """Тест функции get_config с дефолтным именем"""
        config1 = get_config()
        config2 = get_config('default')
        
        # Должны быть один и тот же экземпляр
        assert config1 is config2
