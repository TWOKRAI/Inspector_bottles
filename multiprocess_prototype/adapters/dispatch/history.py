# -*- coding: utf-8 -*-
"""
adapters/dispatch/history.py — snapshot-based undo/redo стек над frozen Project (G.4.1).

ProjectHistory хранит снимки (before, after) каждой команды. Project — frozen
SchemaBase (immutable), поэтому хранение ссылок безопасно (копий не нужно).

Чистый стек: НЕ трогает holder, topology_repo, EventBus, Qt. Восстановление снимка
(holder.set + topology_repo.save → публикация TopologyReplaced) делает
CommandDispatcherOrchestrator — ProjectHistory только хранит и навигирует.

Семантика зеркалит framework ActionBus (snapshot-based с coalescing, max_history):
  - record(): новая запись чистит redo-стек; coalescing мержит burst по coalesce_key.
  - take_undo(): двигает запись undo → redo, возвращает снимок before для восстановления.
  - take_redo(): двигает запись redo → undo, возвращает снимок after.

Refs: plans/2026-05-27_cross-tab-architecture/phase-g.md (Task G.4.1)
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from multiprocess_prototype.domain.entities.project import Project
from multiprocess_prototype.domain.protocols.command_dispatcher import HistoryEntry


@dataclass(frozen=True, slots=True)
class _Snapshot:
    """Внутренняя запись undo-стека: снимки до/после + метаданные команды."""

    before: Project
    after: Project
    label: str
    command_type: str
    timestamp: float
    coalesce_key: str | None


class ProjectHistory:
    """Snapshot-based undo/redo стек над frozen Project.

    undo восстанавливает before предыдущей команды, redo — after. Coalescing
    группирует серии однотипных мутаций (например, тики слайдера) в одну
    undo-запись по совпадающему coalesce_key с вершиной стека.
    """

    def __init__(self, *, max_history: int = 50) -> None:
        self._undo: list[_Snapshot] = []
        self._redo: list[_Snapshot] = []
        self._max_history = max_history

    # ------------------------------------------------------------------
    # Запись
    # ------------------------------------------------------------------

    def record(
        self,
        *,
        before: Project,
        after: Project,
        label: str,
        command_type: str,
        coalesce_key: str | None = None,
    ) -> None:
        """Записать выполненную команду в undo-стек.

        Coalescing: если coalesce_key совпадает с вершиной undo-стека, записи
        сливаются — сохраняется before самой первой (для корректного полного
        отката серии), after берётся новый. Новая запись всегда чистит redo-стек.
        """
        if coalesce_key is not None and self._undo and self._undo[-1].coalesce_key == coalesce_key:
            prev = self._undo[-1]
            self._undo[-1] = _Snapshot(
                before=prev.before,
                after=after,
                label=label,
                command_type=command_type,
                timestamp=time.time(),
                coalesce_key=coalesce_key,
            )
        else:
            self._undo.append(
                _Snapshot(
                    before=before,
                    after=after,
                    label=label,
                    command_type=command_type,
                    timestamp=time.time(),
                    coalesce_key=coalesce_key,
                )
            )
            if len(self._undo) > self._max_history:
                overflow = len(self._undo) - self._max_history
                self._undo = self._undo[overflow:]

        self._redo.clear()

    # ------------------------------------------------------------------
    # Навигация
    # ------------------------------------------------------------------

    def take_undo(self) -> Project | None:
        """Снять верхнюю запись в redo и вернуть снимок before. None если стек пуст."""
        if not self._undo:
            return None
        snap = self._undo.pop()
        self._redo.append(snap)
        return snap.before

    def take_redo(self) -> Project | None:
        """Вернуть запись из redo обратно в undo и вернуть снимок after. None если пуст."""
        if not self._redo:
            return None
        snap = self._redo.pop()
        self._undo.append(snap)
        return snap.after

    # ------------------------------------------------------------------
    # Запросы
    # ------------------------------------------------------------------

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def entries(self, n: int = 20) -> list[HistoryEntry]:
        """Последние n записей undo-стека (от старых к новым) как HistoryEntry."""
        return [
            HistoryEntry(label=s.label, command_type=s.command_type, timestamp=s.timestamp) for s in self._undo[-n:]
        ]

    def clear(self) -> None:
        """Полностью очистить undo/redo стеки."""
        self._undo.clear()
        self._redo.clear()


__all__ = ["ProjectHistory"]
