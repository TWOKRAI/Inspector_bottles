# -*- coding: utf-8 -*-
"""
Основные классы LoggerModule.
"""

from .logger_core import LoggerCore
from .logger_manager import LoggerManager
from .log_config import (
    LogLevel,
    LogScope,
    ScopeName,
    PRESET_SCOPES,
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerRuleSchema,
    LoggerScopeSchema,
)
from .log_types import LogRecord

__all__ = [
    "LoggerCore",
    "LoggerManager",
    "LoggerManagerConfig",
    "LoggerChannelSchema",
    "LoggerScopeSchema",
    "LoggerRuleSchema",
    "LogLevel",
    "LogScope",
    "ScopeName",
    "PRESET_SCOPES",
    "LogRecord",
]
