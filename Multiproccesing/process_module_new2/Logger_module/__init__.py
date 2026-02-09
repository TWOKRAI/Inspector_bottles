"""
Мощная и гибкая система логирования для Python приложений.

Features:
- Гибкая конфигурация через YAML
- Множественные каналы записи (файлы, консоль, HTTP)
- Батчинг для высокой производительности  
- Контекстное логирование
- Фильтрация по областям и модулям
- Декораторы для удобства
- Поддержка асинхронности

Quick Start:
    from logging_system import init_logging, get_logger
    
    # Инициализация
    logger = init_logging(LogConfig.from_yaml("logging_config.yaml"))
    
    # Использование
    logger.info("Application started")
    
    # С контекстом
    with log_context(user_id=123):
        logger.business("INFO", "User action")
"""

from .config import LogConfig, LogLevel, LogScope, ChannelConfig, ScopeConfig
from .manager import LoggerManager, init_logging, get_logger, shutdown_logging
from .decorators import log_call, log_performance, log_context
from .utils import Timer, get_caller_module

__all__ = [
    # Конфигурация
    'LogConfig', 'LogLevel', 'LogScope', 'ChannelConfig', 'ScopeConfig',
    
    # Основной API
    'LoggerManager', 'init_logging', 'get_logger', 'shutdown_logging',
    
    # Декораторы
    'log_call', 'log_performance', 'log_context',
    
    # Утилиты
    'Timer', 'get_caller_module'
]

__version__ = "1.0.0"