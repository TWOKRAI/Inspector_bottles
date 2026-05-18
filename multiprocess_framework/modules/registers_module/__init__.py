# -*- coding: utf-8 -*-
"""Модуль регистров: менеджер, карта маршрутизации, отправка по роутеру."""

from .interfaces import IRegistersManager
from .core.manager import RegistersManager
from .core.field_info import FieldInfo, extract_fields
from .core.dispatch import build_connection_map_from_registers, resolve_dispatch_targets
from .core.routing_map import (
    ROUTING_NOT_FOUND,
    PROCESS_UNREACHABLE,
    MESSAGE_LOST,
    build_routing_map,
    get_routing_for_message,
    send_register_message,
)

__all__ = [
    "IRegistersManager",
    "RegistersManager",
    "FieldInfo",
    "extract_fields",
    "build_connection_map_from_registers",
    "resolve_dispatch_targets",
    "ROUTING_NOT_FOUND",
    "PROCESS_UNREACHABLE",
    "MESSAGE_LOST",
    "build_routing_map",
    "get_routing_for_message",
    "send_register_message",
]
