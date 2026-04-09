# -*- coding: utf-8 -*-
"""
Вспомогательные утилиты для работы с сообщениями.

Внутренние функции, используемые внутри модуля.
"""

import uuid


def generate_message_id(msg_type: str) -> str:
    """
    Генерирует уникальный ID для сообщения.

    Args:
        msg_type: Тип сообщения

    Returns:
        Уникальный ID
    """
    prefix_map = {
        "general": "gen",
        "command": "cmd",
        "log": "log",
        "system": "sys",
        "broadcast": "brd",
        "data": "dat",
        "request": "req",
        "response": "res",
        "event": "evt",
    }
    prefix = prefix_map.get(msg_type, "msg")
    return f"{prefix}_{uuid.uuid4().hex[:8]}"
