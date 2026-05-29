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

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ..commands import ProjectCommand
from ..events import ProjectEvent


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    """Запись истории команд (G.4.1) — для отображения и навигации undo/redo.

    Хранит только проекцию метаданных команды, без снимков Project
    (снимки — внутренняя деталь реализации undo-стека). Domain-чистый dataclass
    без framework-импортов.

    Поля:
      label        — человекочитаемое описание ("AddProcess: camera").
      command_type — дискриминатор команды (type(command).__name__).
      timestamp    — unix time момента записи в историю.
    """

    label: str
    command_type: str
    timestamp: float


class CommandDispatcher(Protocol):
    """Контракт для диспетчеризации команд в domain + история undo/redo (G.4.1).

    Реализации: CommandDispatcherOrchestrator (Phase C + G.4.1 undo/redo),
    FakeCommandDispatcher (тесты).

    G.4.1: undo/redo — snapshot-based поверх ProjectHolder. Восстановление снимка
    проходит через topology_repo.save → store публикует TopologyReplaced
    (store-publishes, G.3) → подписчики (презентеры) делают full reload.
    """

    def dispatch(
        self,
        command: ProjectCommand,
        *,
        coalesce_key: str | None = None,
        undoable: bool = True,
    ) -> list[ProjectEvent]:
        """Выполнить команду. Возвращает список эмитированных событий.

        coalesce_key — группировка undo-записей (серия slider-тиков → одна запись).
        undoable — False для команд вне undo-истории (например, переключение рецепта).
        """
        ...

    def undo(self) -> bool:
        """Отменить последнюю команду. True — что-то отменено, False — стек пуст."""
        ...

    def redo(self) -> bool:
        """Повторить последнюю отменённую команду. True — выполнено, False — стек пуст."""
        ...

    def can_undo(self) -> bool:
        """Есть ли команда для отмены."""
        ...

    def can_redo(self) -> bool:
        """Есть ли команда для повтора."""
        ...

    def history(self, n: int = 20) -> list[HistoryEntry]:
        """Последние n записей истории (от старых к новым)."""
        ...

    def clear_history(self) -> None:
        """Полностью очистить undo/redo историю."""
        ...

    def add_change_callback(self, cb: Callable[[], None]) -> None:
        """Подписаться на уведомления об изменении истории (dispatch/undo/redo/clear).

        G.4.4: UI (кнопки undo/redo, History-вкладка) рефрешит состояние по
        этому колбэку. Позволяет диспетчеру структурно удовлетворять
        framework-протоколу `UndoRedoController`.
        """
        ...


__all__ = [
    "CommandDispatcher",
    "HistoryEntry",
]
