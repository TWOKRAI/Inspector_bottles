# -*- coding: utf-8 -*-
"""
message_module — универсальный транспортный протокол системы.

Единый «язык» общения между менеджерами и процессами.
Все модули системы создают и получают сообщения через этот модуль.

Публичный API — импортируйте отсюда:

    from multiprocess_framework.modules.message_module import Message, MessageType, MessageAdapter
    from multiprocess_framework.modules.message_module import IMessage, IMessageFactory
    from multiprocess_framework.modules.message_module.interfaces import IMessage          # для type hints
"""

# --- Основной класс ---
from .core import Message

# --- Фабрики (удалён класс MessageFactory, оставлены функции для удобства) ---
from .factories import create_message, parse_message

# --- Типы и перечисления ---
from .types import MessageType, Priority, LogLevel, MessageValidationError

# --- Pydantic-схемы (опционально, для валидации) ---
from .schemas import BaseMessageSchema, CommandMessageSchema, LogMessageSchema

# --- Адаптер (для использования в процессах/менеджерах) ---
from .adapters import MessageAdapter

# --- Публичные интерфейсы (для type hints и моков) ---
from .interfaces import IMessage, IMessageFactory

__all__ = [
    # Основной класс
    "Message",
    # Адаптер
    "MessageAdapter",
    # Фабричные функции
    "create_message",
    "parse_message",
    # Типы
    "MessageType",
    "Priority",
    "LogLevel",
    "MessageValidationError",
    # Pydantic-схемы
    "BaseMessageSchema",
    "CommandMessageSchema",
    "LogMessageSchema",
    # Интерфейсы (публичный контракт)
    "IMessage",
    "IMessageFactory",
]
