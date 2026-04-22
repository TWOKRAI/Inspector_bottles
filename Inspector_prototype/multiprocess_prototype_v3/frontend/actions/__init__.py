# -*- coding: utf-8 -*-
"""
actions — модуль Action-схемы и ActionBuilder.

Action — неизменяемая единица изменения состояния.
ActionBuilder — фабрика для создания Action с корректными патчами.
"""
from .schemas import Action, ActionType
from .builder import ActionBuilder
from .bus import ActionBus, ActionHandler, IRegistersManagerGui

__all__ = [
    "Action",
    "ActionType",
    "ActionBuilder",
    "ActionBus",
    "ActionHandler",
    "IRegistersManagerGui",
]
