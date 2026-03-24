# -*- coding: utf-8 -*-
"""
Вспомогательные утилиты для работы с сообщениями.

Внутренние функции, используемые внутри модуля.
"""

import uuid
from typing import TYPE_CHECKING
from ..types.message_types import MessageType, MESSAGE_TYPE_DEFAULTS

if TYPE_CHECKING:
    from .core.message import Message


def generate_message_id(msg_type: str) -> str:
    """
    Генерирует уникальный ID для сообщения.
    
    Внутренняя функция - используется только внутри модуля.
    
    Args:
        msg_type: Тип сообщения
        
    Returns:
        Уникальный ID
    """
    prefix_map = {
        'general': 'gen',
        'command': 'cmd',
        'log': 'log',
        'system': 'sys',
        'broadcast': 'brd',
        'data': 'dat',
        'request': 'req',
        'response': 'res',
        'event': 'evt',
    }
    prefix = prefix_map.get(msg_type, 'msg')
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def apply_type_defaults(message: 'Message') -> None:
    """
    Применяет дефолтные значения для конкретного типа сообщения.
    
    Внутренняя функция - используется только внутри модуля.
    
    Args:
        message: Сообщение для применения дефолтов
    """
    try:
        msg_type = MessageType(message.type)
        defaults = MESSAGE_TYPE_DEFAULTS.get(msg_type, {})
        
        # Применяем дефолты только если значение не было задано
        if 'channel' in defaults and message.channel is None:
            message.channel = defaults['channel']
        
        if 'targets' in defaults and not message.targets:
            message.targets = defaults['targets']
        
        if 'routers' in defaults:
            message.routers = defaults['routers']
            
    except ValueError:
        # Неизвестный тип, используем дефолты
        pass

