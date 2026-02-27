"""
Тесты для конфигурации логирования.

Проверяет:
- Создание конфигурации из словаря
- Загрузку из YAML
- Валидацию уровней и областей
- Конфигурацию каналов и областей
"""
import pytest
import tempfile
from pathlib import Path

from multiprocess_framework.modules.Logger_module.config import (
    LogConfig,
    LogLevel,
    LogScope,
    ChannelConfig,
    ScopeConfig,
    ModuleConfig
)


class TestLogConfig:
    """Тесты для LogConfig"""
    
    def test_default_config(self):
        """Тест создания конфигурации по умолчанию"""
        config = LogConfig()
        
        assert config.app_name == "unknown_app"
        assert config.default_level == LogLevel.INFO
        assert config.enable_batching
        assert config.batch_size == 100
    
    def test_config_from_dict(self):
        """Тест создания конфигурации из словаря"""
        config_dict = {
            'app_name': 'test_app',
            'enable_batching': False,
            'batch_size': 50,
            'batch_interval': 2.0,
            'default_level': 'DEBUG',
            'channels': {
                'console': {
                    'type': 'console',
                    'enabled': True,
                    'format': '%(message)s'
                },
                'file': {
                    'type': 'file',
                    'enabled': True,
                    'file_path': 'logs/test.log',
                    'max_size': 1024
                }
            },
            'scopes': {
                'system': {
                    'enabled': True,
                    'min_level': 'INFO',
                    'channels': ['console'],
                    'modules': ['main']
                }
            }
        }
        
        config = LogConfig.from_dict(config_dict)
        
        assert config.app_name == 'test_app'
        assert not config.enable_batching
        assert config.batch_size == 50
        assert config.batch_interval == 2.0
        assert config.default_level == LogLevel.DEBUG
        assert len(config.channels) == 2
        assert 'console' in config.channels
        assert 'file' in config.channels
        assert LogScope.SYSTEM in config.scopes
    
    def test_config_from_yaml(self):
        """Тест загрузки конфигурации из YAML"""
        yaml_content = """
app_name: yaml_test_app
enable_batching: true
batch_size: 200
default_level: WARNING
channels:
  console:
    type: console
    enabled: true
scopes:
  business:
    enabled: true
    min_level: INFO
    channels: [console]
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            yaml_path = f.name
        
        try:
            config = LogConfig.from_yaml(yaml_path)
            
            assert config.app_name == 'yaml_test_app'
            assert config.enable_batching
            assert config.batch_size == 200
            assert config.default_level == LogLevel.WARNING
            assert 'console' in config.channels
            assert LogScope.BUSINESS in config.scopes
        finally:
            Path(yaml_path).unlink()
    
    def test_config_from_nonexistent_yaml(self):
        """Тест загрузки несуществующего YAML файла"""
        config = LogConfig.from_yaml('nonexistent.yaml')
        
        # Должна вернуться конфигурация по умолчанию
        assert config.app_name == "unknown_app"
    
    def test_get_scope_config(self):
        """Тест получения конфигурации области"""
        config = LogConfig()
        
        # Тест существующей области
        config.scopes[LogScope.SYSTEM] = ScopeConfig(
            scope=LogScope.SYSTEM,
            enabled=True,
            min_level=LogLevel.ERROR
        )
        
        scope_config = config.get_scope_config(LogScope.SYSTEM)
        assert scope_config.scope == LogScope.SYSTEM
        assert scope_config.min_level == LogLevel.ERROR
        
        # Тест несуществующей области (должна вернуться по умолчанию)
        scope_config = config.get_scope_config(LogScope.BUSINESS)
        assert scope_config.scope == LogScope.BUSINESS
        assert scope_config.min_level == config.default_level


class TestScopeConfig:
    """Тесты для ScopeConfig"""
    
    def test_should_log(self):
        """Тест метода should_log"""
        scope_config = ScopeConfig(
            scope=LogScope.SYSTEM,
            enabled=True,
            min_level=LogLevel.INFO
        )
        
        # Должно логировать INFO и выше
        assert scope_config.should_log(LogLevel.INFO, 'test_module')
        assert scope_config.should_log(LogLevel.WARNING, 'test_module')
        assert scope_config.should_log(LogLevel.ERROR, 'test_module')
        
        # Не должно логировать DEBUG
        assert not scope_config.should_log(LogLevel.DEBUG, 'test_module')
        
        # Если область выключена
        scope_config.enabled = False
        assert not scope_config.should_log(LogLevel.INFO, 'test_module')
    
    def test_module_filtering(self):
        """Тест фильтрации по модулям"""
        scope_config = ScopeConfig(
            scope=LogScope.SYSTEM,
            enabled=True,
            min_level=LogLevel.INFO,
            modules={'allowed_module'}
        )
        
        # Должно логировать только для разрешенного модуля
        assert scope_config.should_log(LogLevel.INFO, 'allowed_module')
        assert not scope_config.should_log(LogLevel.INFO, 'forbidden_module')
        
        # Если модули не указаны - логирует все
        scope_config.modules = set()
        assert scope_config.should_log(LogLevel.INFO, 'any_module')


class TestChannelConfig:
    """Тесты для ChannelConfig"""
    
    def test_channel_config_defaults(self):
        """Тест значений по умолчанию для канала"""
        config = ChannelConfig(name='test', type='console')
        
        assert config.name == 'test'
        assert config.type == 'console'
        assert config.enabled
        assert config.format is not None
        assert config.max_size == 10 * 1024 * 1024
        assert config.backup_count == 5
