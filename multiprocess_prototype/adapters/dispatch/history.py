# -*- coding: utf-8 -*-
"""
adapters/dispatch/history.py — snapshot-based undo/redo стек над frozen Project (G.4.1).

ProjectHistory — доменная привязка framework-блока ``SnapshotHistory[T]``
(carve-out 2026-06-18): generic-логика стека (record/coalesce/undo/redo/max_history)
вынесена во framework (``multiprocess_framework.modules.actions_module``), здесь — только
параметризация типом ``Project`` и проекция ``entries()`` в доменный ``HistoryEntry``.
``Project`` — frozen SchemaBase (immutable), поэтому хранение ссылок безопасно.

Чистый стек: НЕ трогает holder, topology_repo, EventBus, Qt. Восстановление снимка
(holder.set + topology_repo.save → публикация TopologyReplaced) делает
``CommandDispatcherOrchestrator`` — ProjectHistory только хранит и навигирует.

Refs: plans/2026-05-27_cross-tab-architecture/phase-g.md (Task G.4.1);
      docs/audits/2026-06-18_command-undo-system.md (вынос SnapshotHistory[T] во framework)
"""

from __future__ import annotations

from multiprocess_framework.modules.actions_module import SnapshotHistory

from multiprocess_prototype.domain.entities.project import Project
from multiprocess_prototype.domain.protocols import HistoryEntry


class ProjectHistory(SnapshotHistory[Project]):
    """Snapshot-based undo/redo над frozen Project — доменная привязка SnapshotHistory[T].

    Наследует стек-логику (record/take_undo/take_redo/can_undo/can_redo/clear, coalescing,
    max_history) из framework ``SnapshotHistory[Project]``. Переопределяет только
    ``entries()`` — проецирует generic ``SnapshotEntry`` в доменный ``HistoryEntry``
    (тип контракта ``CommandDispatcher``).
    """

    def entries(self, n: int = 20) -> list[HistoryEntry]:
        """Последние n записей как доменный HistoryEntry. n=0 → все записи."""
        return [
            HistoryEntry(label=e.label, command_type=e.command_type, timestamp=e.timestamp) for e in super().entries(n)
        ]


__all__ = ["ProjectHistory"]
