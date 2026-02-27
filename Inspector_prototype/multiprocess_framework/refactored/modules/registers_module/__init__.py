# -*- coding: utf-8 -*-
"""Модуль регистров: менеджер, карта маршрутизации, отправка по роутеру."""

from .interfaces import IRegistersManager, IRegistersConverter
from .manager import RegistersManager
from .routing_map import (
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
    "ROUTING_NOT_FOUND",
    "PROCESS_UNREACHABLE",
    "MESSAGE_LOST",
    "build_routing_map",
    "get_routing_for_message",
    "send_register_message",
]
