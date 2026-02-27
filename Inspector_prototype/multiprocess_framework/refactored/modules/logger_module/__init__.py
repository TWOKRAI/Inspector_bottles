"""
Logger Module (Refactored) - Модуль системы логирования.

Предоставляет гибкую и производительную систему логирования с поддержкой:
- Множественных каналов записи (файл, консоль, HTTP)
- Батчинга для оптимизации производительности
- Контекстного логирования
- Фильтрации по областям и модулям
- Динамической конфигурации
- Совместимости с multiprocessing (без блокировок)
"""

from .core.logger_manager import LoggerManager, get_logger, init_logging, shutdown_logging
from .core.log_config import LogConfig, LogLevel, LogScope, ChannelConfig, ScopeConfig, ModuleConfig
from .channels.log_channel import LogChannel, FileChannel, ConsoleChannel, HttpChannel, create_channel
from .adapters.logger_adapter import LoggerAdapter
from .interfaces import ILoggerManager, ILogChannel

__all__ = [
    # Основные классы
    "LoggerManager",
    "LogConfig",
    "LogLevel",
    "LogScope",
    "ChannelConfig",
    "ScopeConfig",
    "ModuleConfig",
    # Каналы
    "LogChannel",
    "FileChannel",
    "ConsoleChannel",
    "HttpChannel",
    "create_channel",
    # Адаптеры
    "LoggerAdapter",
    # Интерфейсы
    "ILoggerManager",
    "ILogChannel",
    # Глобальные функции
    "get_logger",
    "init_logging",
    "shutdown_logging",
]

__version__ = "2.0.0"

