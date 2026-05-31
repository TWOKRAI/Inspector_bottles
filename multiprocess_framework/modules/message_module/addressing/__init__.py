# -*- coding: utf-8 -*-
"""
addressing — иерархическая адресация получателей в ``Message.targets``.

Публичный API парсинга/валидации dotted-адреса ``process[.worker[.…]]``.
Подробности контракта — в :mod:`.address`.
"""

from .address import (
    BROADCAST_TARGETS,
    SEPARATOR,
    is_broadcast,
    normalize_targets,
    process_of,
    split_address,
    validate_address,
    worker_of,
)

__all__ = [
    "SEPARATOR",
    "BROADCAST_TARGETS",
    "is_broadcast",
    "validate_address",
    "split_address",
    "process_of",
    "worker_of",
    "normalize_targets",
]
