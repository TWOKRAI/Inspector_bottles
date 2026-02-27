"""
Тесты для LoggerAdapter.

Проверяет:
- Инициализацию адаптера
- Конвертацию уровней логирования
- Работу с разными областями логирования
- Интеграцию с процессом
"""
import pytest
from unittest.mock import Mock

from multiprocess_framework.modules.Logger_module import (
    LoggerManager,
    LogConfig,
    LogLevel,
    LogScope,
    LoggerAdapter,
    ChannelConfig,
    ScopeConfig
)


class TestLoggerAdapter:
    """Тесты для LoggerAdapter"""
    
    def test_initialization(self, logger_adapter):
        """Тест инициализации адаптера"""
        assert logger_adapter is not None
        assert logger_adapter.setup()
        assert logger_adapter.is_initialized()
    
    def test_level_conversion(self, logger_adapter):
        """Тест конвертации уровней логирования"""
        # Тест строкового уровня
        result = logger_adapter.log("INFO", "Test message")
        assert result
        
        # Тест LogLevel enum
        result = logger_adapter.log(LogLevel.INFO, "Test message")
        assert result
        
        # Тест lowercase (формат Message_module)
        result = logger_adapter.log("info", "Test message")
        assert result
    
    def test_convenience_methods(self, logger_adapter, log_config):
        """Тест удобных методов логирования"""
        logger_adapter.debug("Debug message")
        logger_adapter.info("Info message")
        logger_adapter.warning("Warning message")
        logger_adapter.error("Error message")
        logger_adapter.critical("Critical message")
        
        # Проверяем, что все сообщения обработаны
        stats = logger_adapter.manager.get_stats()
        assert stats['messages_processed'] >= 5
    
    def test_scope_methods(self, logger_adapter):
        """Тест методов для разных областей"""
        logger_adapter.system(LogLevel.INFO, "System message")
        logger_adapter.business(LogLevel.INFO, "Business message")
        logger_adapter.performance(LogLevel.WARNING, "Performance message")
        logger_adapter.audit(LogLevel.INFO, "Audit message")
        logger_adapter.security(LogLevel.INFO, "Security message")
        
        stats = logger_adapter.manager.get_stats()
        assert stats['messages_processed'] >= 5
    
    def test_context_parameter(self, logger_adapter):
        """Тест параметра context"""
        logger_adapter.info("Message", context="custom_module")
        
        stats = logger_adapter.manager.get_stats()
        assert stats['messages_processed'] >= 1
    
    def test_default_module_from_process(self, logger_adapter):
        """Тест автоматического определения модуля из процесса"""
        # Адаптер должен использовать имя процесса как модуль по умолчанию
        logger_adapter.info("Message")
        
        # Проверяем, что сообщение обработано
        stats = logger_adapter.manager.get_stats()
        assert stats['messages_processed'] >= 1
    
    def test_get_stats(self, logger_adapter):
        """Тест получения статистики"""
        stats = logger_adapter.get_stats()
        
        assert 'adapter_name' in stats
        assert 'initialized' in stats
        assert 'message_routing_enabled' in stats
        assert 'manager_stats' in stats
    
    def test_message_routing_setting(self, logger_adapter):
        """Тест настройки маршрутизации через Message_module"""
        # По умолчанию выключено
        assert not logger_adapter.enable_message_routing
        
        # Включаем
        logger_adapter.set_message_routing(True)
        assert logger_adapter.enable_message_routing
        
        # Выключаем
        logger_adapter.set_message_routing(False)
        assert not logger_adapter.enable_message_routing
