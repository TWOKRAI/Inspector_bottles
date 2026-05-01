# -*- coding: utf-8 -*-
"""
actions -- Action-система фреймворка.

Action -- неизменяемая единица изменения состояния.
ActionBuilder -- базовая фабрика (generic core).
ActionBus -- шина выполнения с undo/redo и coalescing.
"""
from .schemas import Action
from .builder import ActionBuilder
from .bus import ActionBus, ActionHandler, IRegistersManagerGui

__all__ = ["Action", "ActionBuilder", "ActionBus", "ActionHandler", "IRegistersManagerGui"]
