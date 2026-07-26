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


#: Значения priority, которые понимает ``BatchBuffer.enqueue``
#: (channel_routing_module/buffers/batch_buffer.py).
URGENT_PRIORITY = "urgent"
NORMAL_PRIORITY = "normal"

#: Ранг, начиная с которого запись считается аварийной и не должна ждать пачку.
_URGENT_RANK = LEVEL_ORDER.index("ERROR")


def buffer_priority(level) -> str:
    """Приоритет ``BatchBuffer`` для уровня: ERROR/CRITICAL → ``urgent``, иначе ``normal``.

    Ф0.1 плана ``observability-unified-routing``. До этой правки ни ``LoggerCore.log()``,
    ни severity-путь ``ErrorManager.log()`` не передавали priority в ``enqueue`` —
    поэтому ветка немедленного сброса в ``BatchBuffer`` была недостижима, а окно
    потери crash-лога при аварийном завершении процесса равнялось ``batch_interval``
    (1.0 с у логгера, 0.5 с у ошибок).

    ВРЕМЕННАЯ МЕРА: снимается задачей 0.9 (floor ошибок, вариант B) — там путь
    error/critical становится синхронным и конфиго-независимым.
    """
    return URGENT_PRIORITY if level_rank(level) >= _URGENT_RANK else NORMAL_PRIORITY
