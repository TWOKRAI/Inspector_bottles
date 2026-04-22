"""Общие утилиты для backend-процессов прототипа."""
from __future__ import annotations

from typing import Any, Callable, Dict


def apply_register_update(
    data: dict,
    register_name: str,
    handlers: Dict[str, Callable[[Any], Any]],
) -> bool:
    """Применить register_update сообщение к состоянию процесса.

    Args:
        data: payload register_update (register_name, field_name, value)
        register_name: ожидаемое имя регистра для матчинга
        handlers: {field_name: callable(value)} маппинг

    Returns:
        True если обработано, False если register_name не совпал.
    """
    if data.get("register_name") != register_name:
        return False
    field = data.get("field_name")
    value = data.get("value")
    handler = handlers.get(field)
    if handler:
        handler(value)
        return True
    return False


def message_as_dict(msg) -> dict:
    """Конвертировать сообщение в dict (dict passthrough, .to_dict() fallback)."""
    if msg is None:
        return {}
    if isinstance(msg, dict):
        return msg
    if hasattr(msg, "to_dict"):
        return msg.to_dict()
    return {}
