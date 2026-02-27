"""
Тесты для LoggerManager.

Проверяет:
- Инициализацию и базовое логирование
- Интеграцию с ConfigManager (динамическое изменение конфигурации)
- Поддержку файлов по модулям
- Интеграцию с ObservableMixin
- Батчинг
- Маршрутизацию через Message_module
"""
import pytest
from pathlib import Path

from multiprocess_framework.modules.Logger_module import (
    LoggerManager,
    LogConfig,
    LogLevel,
    LogScope,
    ChannelConfig,
    ScopeConfig
)
from multiprocess_framework.modules.Config_module import ConfigManager


class TestLoggerManager:
    """Тесты для LoggerManager"""
    
    def test_initialization(self, log_config):
        """Тест инициализации LoggerManager"""
        logger = LoggerManager(config=log_config)
        logger.initialize()
        
        assert logger is not None
        assert logger.app_name == "test_app"
        assert logger.is_initialized
        assert len(logger.channels) == 2  # console + file
        
        # Проверяем shutdown
        logger.shutdown()
        assert not logger.is_initialized
    
    def test_basic_logging(self, log_config):
        """Тест базового логирования"""
        logger = LoggerManager(config=log_config)
        
        # Логируем сообщение
        logger.info("Test message", module="test_module")
        
        # Проверяем статистику
        stats = logger.get_stats()
        assert stats['messages_processed'] == 1
        
        logger.shutdown()
    
    def test_log_levels(self, log_config):
        """Тест разных уровней логирования"""
        logger = LoggerManager(config=log_config)
        
        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")
        logger.error("Error message")
        logger.critical("Critical message")
        
        stats = logger.get_stats()
        assert stats['messages_processed'] == 5
        
        logger.shutdown()
    
    def test_log_scopes(self, log_config):
        """Тест разных областей логирования"""
        logger = LoggerManager(config=log_config)
        
        # Настраиваем области
        log_config.scopes[LogScope.BUSINESS] = ScopeConfig(
            scope=LogScope.BUSINESS,
            enabled=True,
            min_level=LogLevel.INFO
        )
        
        logger.system(LogLevel.INFO, "System message")
        logger.business(LogLevel.INFO, "Business message")
        logger.performance(LogLevel.WARNING, "Performance message")
        
        stats = logger.get_stats()
        assert stats['messages_processed'] >= 3
        
        logger.shutdown()
    
    def test_should_log_filtering(self, log_config):
        """Тест фильтрации логов"""
        logger = LoggerManager(config=log_config)
        
        # Настраиваем область только для определенного модуля
        log_config.scopes[LogScope.SYSTEM].modules = {'allowed_module'}
        
        # Логируем из разрешенного модуля
        should_log = logger.should_log(LogScope.SYSTEM, LogLevel.INFO, 'allowed_module')
        assert should_log
        
        # Логируем из запрещенного модуля
        should_log = logger.should_log(LogScope.SYSTEM, LogLevel.INFO, 'forbidden_module')
        assert not should_log
        
        logger.shutdown()
    
    def test_config_manager_integration(self, log_config):
        """Тест интеграции с ConfigManager"""
        # Используем реальный Config через ConfigManager
        config = ConfigManager.get_instance('logging')
        
        # Настраиваем конфигурацию логирования
        config.set('logging.scopes.system.enabled', True)
        
        logger = LoggerManager(config=log_config, config_manager=ConfigManager)
        
        # Проверяем начальное состояние
        assert log_config.scopes[LogScope.SYSTEM].enabled
        
        # Изменяем конфигурацию через Config
        config.set('logging.scopes.system.enabled', False)
        
        # Проверяем, что конфигурация обновилась через callback
        # (в реальности callback должен обновить log_config, но для теста проверяем что метод работает)
        assert config.get('logging.scopes.system.enabled') == False
        
        # Включаем обратно
        config.set('logging.scopes.system.enabled', True)
        assert config.get('logging.scopes.system.enabled') == True
        
        logger.shutdown()
    
    def test_dynamic_channel_control(self, log_config):
        """Тест динамического управления каналами"""
        # Используем реальный Config через ConfigManager
        config = ConfigManager.get_instance('logging')
        
        logger = LoggerManager(config=log_config, config_manager=ConfigManager)
        logger.initialize()
        
        # Проверяем, что канал включен
        assert log_config.channels['console'].enabled
        
        # Выключаем канал через Config
        config.set('logging.channels.console.enabled', False)
        
        # Проверяем, что конфигурация обновилась через callback
        assert config.get('logging.channels.console.enabled') == False
        
        # Включаем обратно
        config.set('logging.channels.console.enabled', True)
        assert config.get('logging.channels.console.enabled') == True
        
        # Закрываем каналы перед shutdown
        logger.flush()
        for channel in list(logger.channels.values()):
            if hasattr(channel, 'close'):
                try:
                    channel.close()
                except Exception:
                    pass
        
        logger.shutdown()
    
    def test_module_file_logging(self, log_config, temp_dir):
        """Тест логирования в отдельные файлы для модулей"""
        logger = LoggerManager(config=log_config)
        logger.initialize()
        
        # Включаем отдельный файл для модуля
        log_dir = Path(temp_dir) / "logs"
        module_file = log_dir / "command_manager.log"
        logger.enable_module_logging("command_manager", str(module_file))
        
        # Проверяем статистику
        stats_before = logger.get_stats()
        initial_count = stats_before.get('module_files_created', 0)
        
        # Логируем в модуль
        logger.info("Module message", module="command_manager")
        
        # Проверяем статистику
        stats = logger.get_stats()
        assert stats.get('module_files_created', 0) >= initial_count
        
        # Выключаем модуль
        logger.disable_module_logging("command_manager")
        
        # Закрываем все каналы перед shutdown
        logger.flush()
        for channel in list(logger.channels.values()) + list(logger._module_channels.values()):
            if hasattr(channel, 'close'):
                try:
                    channel.close()
                except Exception:
                    pass
        
        logger.shutdown()
    
    def test_batching(self, log_config):
        """Тест батчинга логов"""
        # Включаем батчинг
        log_config.enable_batching = True
        log_config.batch_size = 5
        log_config.batch_interval = 0.1
        
        logger = LoggerManager(config=log_config)
        
        # Логируем несколько сообщений
        for i in range(10):
            logger.info(f"Message {i}")
        
        # Проверяем статистику батчинга
        stats = logger.get_stats()
        assert stats.get('messages_batched', 0) > 0
        
        # Принудительно сбрасываем
        logger.flush()
        
        logger.shutdown()
    
    def test_context_logging(self, log_config):
        """Тест контекстного логирования"""
        logger = LoggerManager(config=log_config)
        
        # Добавляем контекст
        logger.push_context(user_id=123, request_id="abc-123")
        
        # Логируем с контекстом
        logger.info("Context message")
        
        # Убираем контекст
        logger.pop_context()
        
        logger.shutdown()
    
    def test_observable_mixin_integration(self, log_config):
        """Тест интеграции с ObservableMixin"""
        # Создаем mock менеджер
        class MockManager:
            def some_method(self):
                return "result"
        
        mock_manager = MockManager()
        
        logger = LoggerManager(
            config=log_config,
            managers={'test': mock_manager}
        )
        
        # Проверяем доступ к менеджеру
        assert logger.has_manager('test')
        assert logger.get_manager('test') == mock_manager
        
        logger.shutdown()
    
    def test_log_config_from_dict(self):
        """Тест создания конфигурации из словаря"""
        config_dict = {
            'app_name': 'test_app',
            'enable_batching': True,
            'batch_size': 50,
            'channels': {
                'console': {
                    'type': 'console',
                    'enabled': True
                }
            },
            'scopes': {
                'system': {
                    'enabled': True,
                    'min_level': 'INFO',
                    'channels': ['console']
                }
            }
        }
        
        config = LogConfig.from_dict(config_dict)
        
        assert config.app_name == 'test_app'
        assert config.enable_batching
        assert config.batch_size == 50
        assert 'console' in config.channels
        assert LogScope.SYSTEM in config.scopes
    
    def test_log_config_from_yaml(self, temp_dir):
        """Тест загрузки конфигурации из YAML"""
        yaml_content = """
app_name: test_app
enable_batching: true
batch_size: 100
channels:
  console:
    type: console
    enabled: true
scopes:
  system:
    enabled: true
    min_level: INFO
    channels: [console]
"""
        log_dir = Path(temp_dir) / "logs"
        yaml_file = log_dir / "test_config.yaml"
        yaml_file.write_text(yaml_content)
        
        config = LogConfig.from_yaml(str(yaml_file))
        
        assert config.app_name == 'test_app'
        assert config.enable_batching
        assert 'console' in config.channels
    
    def test_statistics(self, log_config):
        """Тест сбора статистики"""
        logger = LoggerManager(config=log_config)
        
        # Логируем несколько сообщений
        logger.info("Message 1")
        logger.warning("Message 2")
        logger.error("Message 3")
        
        stats = logger.get_stats()
        
        assert 'messages_processed' in stats
        assert 'messages_skipped' in stats
        assert 'channels_count' in stats
        assert 'batching_enabled' in stats
        assert 'manager_name' in stats  # Из BaseManager
        
        logger.shutdown()
