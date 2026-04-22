# -*- coding: utf-8 -*-
"""
Logger Module (Refactored) - Модуль системы логирования.

Предоставляет гибкую и производительную систему логирования с поддержкой:
- Множественных каналов записи (файл, консоль, HTTP)
- Батчинга для оптимизации производительности
- Фильтрации по областям и модулям
- Динамической конфигурации (SchemaBase / LoggerManagerConfig)
- Совместимости с multiprocessing (без блокировок)
"""

from .configs import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerModuleSchema,
    LoggerScopeSchema,
)
from .core.log_config import LogLevel, LogScope
from .core.logger_manager import LoggerManager, get_logger, init_logging, shutdown_logging
from .channels.log_channel import LogChannel, FileChannel, ConsoleChannel, HttpChannel, create_channel
from .adapters.logger_adapter import LoggerAdapter
from .interfaces import ILoggerManager, ILogChannel

__all__ = [
    "LoggerManager",
    "LoggerManagerConfig",
    "LoggerChannelSchema",
    "LoggerScopeSchema",
    "LoggerModuleSchema",
    "LogLevel",
    "LogScope",
    "LogChannel",
    "FileChannel",
    "ConsoleChannel",
    "HttpChannel",
    "create_channel",
    "LoggerAdapter",
    "ILoggerManager",
    "ILogChannel",
    "get_logger",
    "init_logging",
    "shutdown_logging",
]

__version__ = "2.0.0"
