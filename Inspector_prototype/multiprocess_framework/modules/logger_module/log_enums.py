# -*- coding: utf-8 -*-
"""Уровни и области логирования — enum для рантайма LoggerManager (без Pydantic)."""

from enum import Enum


class LogLevel(Enum):
    """Уровни логирования."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogScope(Enum):
    """Области логирования (значение — строка для сериализации)."""

    SYSTEM = "system"
    BUSINESS = "business"
    PERFORMANCE = "perf"
    AUDIT = "audit"
    SECURITY = "security"
    DEBUG = "debug"
