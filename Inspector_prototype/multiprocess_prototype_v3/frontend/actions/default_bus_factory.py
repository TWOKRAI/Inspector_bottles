# -*- coding: utf-8 -*-
"""
default_bus_factory — фабрика ActionBus со стандартными handlers.

Создаётся один раз при инициализации frontend и прокидывается через FrontendAppContext.
"""
from __future__ import annotations

from .bus import ActionBus
from .schemas import ActionType
from .handlers.field_set_handler import FieldSetHandler


def create_default_action_bus(rm) -> ActionBus:
    """
    Создать ActionBus с зарегистрированными стандартными handlers.

    Args:
        rm: RegistersManager (IRegistersManagerGui) или None в тестах.

    Returns:
        ActionBus с зарегистрированным FieldSetHandler для FIELD_SET.
    """
    bus = ActionBus(rm)
    bus.register_handler(ActionType.FIELD_SET, FieldSetHandler())
    return bus
