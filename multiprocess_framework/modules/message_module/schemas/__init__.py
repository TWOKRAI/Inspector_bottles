# -*- coding: utf-8 -*-
"""
Pydantic-схемы для строгой валидации сообщений.

BaseMessageSchema — алиас на Message (обратная совместимость с планом 07).
"""

from ..core.message import Message as BaseMessageSchema
from .command import CommandMessageSchema
from .log import LogMessageSchema

__all__ = [
    "BaseMessageSchema",
    "CommandMessageSchema",
    "LogMessageSchema",
]
