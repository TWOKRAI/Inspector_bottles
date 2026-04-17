"""Universal register_update dispatcher for all services."""

from __future__ import annotations

from typing import Any, Callable, Dict


def apply_register_update(
    data: dict,
    register_name: str,
    handlers: Dict[str, Callable[[Any], Any]],
) -> bool:
    """Apply a register_update message to process state.

    Args:
        data: register_update payload (register_name, field_name, value)
        register_name: expected register name to match
        handlers: {field_name: callable(value)} mapping

    Returns:
        True if handled, False if register_name didn't match.
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
