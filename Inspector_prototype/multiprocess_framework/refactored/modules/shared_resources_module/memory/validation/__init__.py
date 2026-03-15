"""Validation — валидация доступа к SharedMemory."""

from .access import (
    clear_memory_slot,
    validate_memory_access,
    validate_write_operation,
)

__all__ = [
    "clear_memory_slot",
    "validate_memory_access",
    "validate_write_operation",
]
