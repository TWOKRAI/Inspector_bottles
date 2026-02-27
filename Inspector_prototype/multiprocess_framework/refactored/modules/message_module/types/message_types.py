"""
Типы сообщений для системы межпроцессного взаимодействия.

Определяет типы, приоритеты и схемы сообщений.
"""

from enum import Enum
from dataclasses import dataclass, field
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


@dataclass
class MessageSchema:
    """
    Базовая схема сообщения.
    Определяет обязательные и опциональные поля для всех типов сообщений.
    """
    # Обязательные поля
    id: str
    type: str
    sender: str
    targets: List[str]
    timestamp: float
    
    # Опциональные поля с дефолтными значениями
    priority: str = "normal"
    routers: List[str] = field(default_factory=lambda: ["internal"])
    channel: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Специфичные поля для разных типов сообщений
    # GENERAL
    content: Any = None
    
    # COMMAND
    command: Optional[str] = None
    args: Dict[str, Any] = field(default_factory=dict)
    need_ack: bool = False
    
    # LOG
    level: Optional[str] = None
    message: Optional[str] = None
    module: str = "main"
    
    # SYSTEM
    action: Optional[str] = None
    data: Any = None
    
    # BROADCAST
    exclude: List[str] = field(default_factory=list)
    
    # DATA
    data_type: Optional[str] = None
    use_shared_memory: bool = False
    memory_key: Optional[str] = None
    
    # REQUEST
    request_type: Optional[str] = None
    query: Any = None
    timeout: float = 5.0
    
    # RESPONSE
    request_id: Optional[str] = None
    success: bool = True
    result: Any = None
    error: Optional[str] = None
    
    # EVENT
    event_type: Optional[str] = None
    event_data: Any = None


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

# Список всех допустимых полей сообщения (из MessageSchema)
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

