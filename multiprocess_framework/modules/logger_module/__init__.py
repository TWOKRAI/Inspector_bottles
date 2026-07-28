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
from .channels.log_channel import (
    LogChannel,
    FileChannel,
    ConsoleChannel,
    HttpChannel,
    create_channel,
    register_sink_factory,
    get_registered_sink_types,
)
from .channels.router_push_channel import RouterPushChannel
from ..channel_routing_module.levels import ERROR_RANK, LEVEL_ORDER, is_error_level, level_rank

# Ранги переехали в общую базу (Ф0.6/R6); здесь остаются в публичном экспорте
# logger_module — исторические потребители не обязаны знать о переезде.
from .core.error_floor import ErrorFloor, get_error_floor, reset_error_floors
from .adapters.std_facade import StdLoggerFacade, get_std_logger
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
    "register_sink_factory",
    "get_registered_sink_types",
    "RouterPushChannel",
    "LEVEL_ORDER",
    "level_rank",
    "ERROR_RANK",
    "is_error_level",
    "ErrorFloor",
    "get_error_floor",
    "reset_error_floors",
    "StdLoggerFacade",
    "get_std_logger",
    "ILoggerManager",
    "ILogChannel",
    "get_logger",
    "init_logging",
    "shutdown_logging",
]

__version__ = "2.0.0"
