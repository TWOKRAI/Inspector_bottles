# -*- coding: utf-8 -*-
"""
addressing — иерархическая адресация получателей в ``Message.targets``.

Публичный API парсинга/валидации dotted-адреса ``process[.worker[.…]]``.
Подробности контракта — в :mod:`.address`.
"""

from .address import (
    BROADCAST_TARGETS,
    SEPARATOR,
    depth,
    is_broadcast,
    join_address,
    normalize_targets,
    process_of,
    split_address,
    subpath_of,
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
    "subpath_of",
    "depth",
    "join_address",
    "normalize_targets",
]
