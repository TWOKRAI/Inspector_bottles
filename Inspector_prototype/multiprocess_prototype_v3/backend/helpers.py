"""Общие утилиты для backend-процессов прототипа."""
from __future__ import annotations


def message_as_dict(msg) -> dict:
    """Конвертировать сообщение в dict (dict passthrough, .to_dict() fallback)."""
    if msg is None:
        return {}
    if isinstance(msg, dict):
        return msg
    if hasattr(msg, "to_dict"):
        return msg.to_dict()
    return {}
