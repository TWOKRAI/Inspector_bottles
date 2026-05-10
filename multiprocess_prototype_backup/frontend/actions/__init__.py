# -*- coding: utf-8 -*-
"""
actions -- модуль Action-схемы и ActionBuilder.

Action -- неизменяемая единица изменения состояния.
ActionBuilder -- фабрика для создания Action с корректными патчами (domain-версия).
AppActionBuilder -- domain-наследник с расширенными методами.
"""
from .schemas import Action, ActionType, AppActionType
from .builder import ActionBuilder
from .app_action_builder import AppActionBuilder
from .bus import ActionBus, ActionHandler, IRegistersManagerGui

__all__ = [
    "Action",
    "ActionType",
    "AppActionType",
    "ActionBuilder",
    "AppActionBuilder",
    "ActionBus",
    "ActionHandler",
    "IRegistersManagerGui",
]
