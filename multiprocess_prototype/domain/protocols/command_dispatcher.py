# -*- coding: utf-8 -*-
"""
domain/protocols/command_dispatcher.py — Protocol для диспетчера команд.

CommandDispatcher — точка входа для presenter'а: отправить ProjectCommand,
получить список результирующих ProjectEvent.

В Phase B — только Protocol. Адаптер поверх существующего ActionBus создаётся
в Phase C. Реальная «чистая функция» Project.apply() является основой —
CommandDispatcher оборачивает её вместе с EventBus в Phase D.
"""

from __future__ import annotations

from typing import Protocol

from ..commands import ProjectCommand
from ..events import ProjectEvent


class CommandDispatcher(Protocol):
    """Контракт для диспетчеризации команд в domain.

    Реализации: CommandDispatcherFromActionBus (Phase C), _FakeCommandDispatcher (тесты).
    """

    def dispatch(self, command: ProjectCommand) -> list[ProjectEvent]:
        """Выполнить команду. Возвращает список эмитированных событий."""
        ...


__all__ = [
    "CommandDispatcher",
]
