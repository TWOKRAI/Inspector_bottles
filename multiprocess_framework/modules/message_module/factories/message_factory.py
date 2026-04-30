# -*- coding: utf-8 -*-
"""
Фабрика сообщений.

Публичные функции для создания сообщений различными способами.
"""

import json
from typing import Union, Dict, Any

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

from ..core.message import Message
from ..types import MessageType


def create_message(type: Union[MessageType, str], sender: str, **kwargs) -> Message:
    """
    Удобная функция для создания сообщений.
    Алиас для Message.create().
    
    Args:
        type: Тип сообщения
        sender: Отправитель
        **kwargs: Дополнительные параметры
        
    Returns:
        Экземпляр сообщения
    """
    return Message.create(type=type, sender=sender, **kwargs)


def parse_message(data: Union[str, Dict[str, Any]]) -> Message:
    """
    Парсит сообщение из строки или словаря.
    Автоматически определяет формат (JSON, YAML, dict).
    
    Args:
        data: Данные для парсинга
        
    Returns:
        Экземпляр сообщения
    """
    if isinstance(data, dict):
        return Message.from_dict(data)
    
    # Пробуем JSON
    try:
        return Message.from_json(data)
    except (json.JSONDecodeError, TypeError):
        pass
    
    # Пробуем YAML
    if YAML_AVAILABLE:
        try:
            return Message.from_yaml(data)
        except Exception:
            pass
    
    raise ValueError("Unable to parse message from provided data")

