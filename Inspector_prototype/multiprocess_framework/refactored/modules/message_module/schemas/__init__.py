"""
Схемы сообщений (Pydantic v2).

Подмодуль для определения схем валидации сообщений.
Позволяет создавать разные схемы для разных типов сообщений.
"""

from .base import BaseMessageSchema
from .command import CommandMessageSchema
from .log import LogMessageSchema

__all__ = [
    'BaseMessageSchema',
    'CommandMessageSchema',
    'LogMessageSchema',
]

