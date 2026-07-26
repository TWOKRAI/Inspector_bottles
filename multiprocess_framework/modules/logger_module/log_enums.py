# -*- coding: utf-8 -*-
"""Уровни и области логирования — enum для рантайма LoggerManager (без Pydantic).

Ранги уровней (``LEVEL_ORDER`` / ``level_rank`` / ``is_error_level``) здесь
БОЛЬШЕ НЕ ЖИВУТ: они общее хозяйство трёх плоскостей наблюдаемости и переехали
в ``channel_routing_module.levels`` (Ф0.6, резидуал R6). База не имеет права
зависеть от своего потомка, а tap-механика с порогом уровня поднята именно в
базу. Здесь остались только enum'ы формата лог-записи — статистике они не нужны.
"""

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
