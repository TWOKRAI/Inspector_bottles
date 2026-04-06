# -*- coding: utf-8 -*-
"""Модуль регистров: менеджер, карта маршрутизации, отправка по роутеру."""

from .interfaces import IRegistersManager, IRegistersConverter
from .core.manager import RegistersManager
from .core.connection_map_builder import build_connection_map_from_registers
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
    "IRegistersConverter",
    "RegistersManager",
    "build_connection_map_from_registers",
    "ROUTING_NOT_FOUND",
    "PROCESS_UNREACHABLE",
    "MESSAGE_LOST",
    "build_routing_map",
    "get_routing_for_message",
    "send_register_message",
]
