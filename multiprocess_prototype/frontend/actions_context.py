# -*- coding: utf-8 -*-
"""ActionsContext — связка зависимостей actions/commands domain.

Сейчас содержит только ActionBus (undo/redo + audit middleware), но
структура выбрана единообразно с другими контекстами — добавление
новых зависимостей (CommandRegistry, ShortcutManager и т.п.) пройдёт
без смены сигнатур потребителей.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multiprocess_framework.modules.actions_module.bus import ActionBus


@dataclass(frozen=True)
class ActionsContext:
    """Actions-домен: command/undo bus.

    Attributes:
        bus: ActionBus (центральный диспетчер действий + undo/redo).
    """

    bus: "ActionBus"
