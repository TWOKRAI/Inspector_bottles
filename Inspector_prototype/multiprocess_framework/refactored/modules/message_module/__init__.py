"""
Message Module - Универсальный транспорт для всех сообщений.

Публичный API модуля. Импортируйте отсюда все необходимое.
"""

from .core import Message
from .factories import MessageFactory, create_message, parse_message
from .types import MessageType, Priority, LogLevel, MessageSchema, MessageValidationError
from .schemas import BaseMessageSchema, CommandMessageSchema, LogMessageSchema

__all__ = [
    # Основные классы
    'Message',
    'MessageValidationError',
    # Фабрики
    'MessageFactory',
    'create_message',
    'parse_message',
    # Типы
    'MessageType',
    'Priority',
    'LogLevel',
    'MessageSchema',
    # Схемы (Pydantic)
    'BaseMessageSchema',
    'CommandMessageSchema',
    'LogMessageSchema',
]
