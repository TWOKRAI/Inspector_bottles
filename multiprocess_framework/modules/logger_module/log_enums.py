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


#: Каноничный порядок уровней (растёт по важности). Единый источник для сравнения
#: «level ≥ порог» (log tail, should_log). Строки — как в LogRecord.to_dict().
LEVEL_ORDER = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def level_rank(level) -> int:
    """Числовой ранг уровня (DEBUG=0 … CRITICAL=4). Принимает ``LogLevel`` или строку.

    Неизвестный уровень → 0 (не фильтруем — безопасный дефолт «пропустить»).
    """
    val = getattr(level, "value", level)
    try:
        return LEVEL_ORDER.index(str(val).upper())
    except ValueError:
        return 0
