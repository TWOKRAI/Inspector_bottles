# -*- coding: utf-8 -*-
"""
Типы сообщений для системы межпроцессного взаимодействия.

Определяет типы, приоритеты и схемы сообщений.
"""

from enum import Enum
from typing import Any, Dict, List, Optional


class MessageType(Enum):
    """Типы сообщений в системе."""
    GENERAL = "general"          # Обычное сообщение с произвольным содержимым
    COMMAND = "command"          # Команда для выполнения действия
    LOG = "log"                  # Лог-сообщение для централизованного логирования
    SYSTEM = "system"            # Системное сообщение для управления процессами
    BROADCAST = "broadcast"      # Широковещательное сообщение для всех процессов
    DATA = "data"                # Сообщение с большими данными (может использовать shared memory)
    REQUEST = "request"          # Запрос, ожидающий ответа
    RESPONSE = "response"        # Ответ на запрос
    EVENT = "event"              # Событийное сообщение (pub/sub паттерн)


class Priority(Enum):
    """Приоритеты сообщений."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class LogLevel(Enum):
    """Уровни логирования."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# Конфигурация по умолчанию для каждого типа сообщения
MESSAGE_TYPE_DEFAULTS = {
    MessageType.GENERAL: {
        "channel": "queue",
        "required_fields": ["content"],
    },
    MessageType.COMMAND: {
        "channel": "queue",
        "required_fields": ["command"],
    },
    MessageType.LOG: {
        "channel": "log",
        "targets": ["logger"],
        "routers": ["log"],
        "required_fields": ["level", "message"],
    },
    MessageType.SYSTEM: {
        "channel": "queue",
        "required_fields": ["action"],
    },
    MessageType.BROADCAST: {
        "channel": "broadcast",
        "targets": ["all"],
        "required_fields": ["content"],
    },
    MessageType.DATA: {
        "channel": "queue",
        "required_fields": ["data_type"],
    },
    MessageType.REQUEST: {
        "channel": "queue",
        "required_fields": ["request_type"],
    },
    MessageType.RESPONSE: {
        "channel": "queue",
        "required_fields": ["request_id"],
    },
    MessageType.EVENT: {
        "channel": "broadcast",
        "targets": ["all"],
        "required_fields": ["event_type"],
    },
}


# Поля, которые нужно исключать при сериализации для определенных типов
MESSAGE_TYPE_EXCLUDE_FIELDS = {
    MessageType.LOG: {"routers"},  # Логи не должны показывать routers в dict
}

# Список всех допустимых полей сообщения
# Используется для валидации в __setitem__ и _sync_to_dict
VALID_MESSAGE_FIELDS = {
    'id', 'type', 'sender', 'targets', 'timestamp',
    'priority', 'routers', 'channel', 'metadata',
    'content', 'command', 'args', 'need_ack',
    'level', 'message', 'module', 'action', 'data',
    'exclude', 'data_type', 'use_shared_memory', 'memory_key',
    'request_type', 'query', 'timeout', 'request_id',
    'success', 'result', 'error', 'event_type', 'event_data'
}

