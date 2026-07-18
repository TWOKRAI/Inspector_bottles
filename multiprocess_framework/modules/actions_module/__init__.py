# -*- coding: utf-8 -*-
"""
actions -- строительные блоки undo/redo фреймворка (под контракт UndoRedoController).

Две реализации одного контракта (разные tier'ы, см. docs/audits/2026-06-18_command-undo-system.md):
  PATCH-движок:
    Action -- неизменяемая единица изменения состояния (forward/backward patch).
    ActionBuilder -- базовая фабрика (generic core).
    ActionBus -- шина выполнения с undo/redo и coalescing (для простых/сложных проектов).
  SNAPSHOT-блок:
    SnapshotHistory[T] -- generic snapshot-стек над immutable-агрегатом T (для проектов
    с чистым immutable-агрегатом; прототип строит ProjectHistory = SnapshotHistory[Project]).
    SnapshotEntry -- проекция метаданных записи стека.
"""

from .schemas import Action
from .builder import ActionBuilder
from .bus import ActionBus, ActionHandler
from .interfaces import IRegistersManagerGui
from .snapshot_history import SnapshotEntry, SnapshotHistory

__all__ = [
    "Action",
    "ActionBuilder",
    "ActionBus",
    "ActionHandler",
    "IRegistersManagerGui",
    "SnapshotHistory",
    "SnapshotEntry",
]
