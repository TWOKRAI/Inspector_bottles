# -*- coding: utf-8 -*-
"""
snapshot_history -- generic snapshot-based undo/redo стек (строительный блок конструктора).

SnapshotHistory[T] -- хранит снимки (before, after) каждой мутации immutable-агрегата T,
навигирует undo/redo, склеивает серии по coalesce_key, ограничивает глубину max_history.
Qt-free, без app-импортов: параметризуется типом агрегата T (например, Project в прототипе).

Это SNAPSHOT-реализация-блок под контракт ``UndoRedoController``
(``frontend_module/.../tab_layout_protocol.py``) — рядом с PATCH-движком ``ActionBus``.
Контроллер (orchestrator) строится ПОВЕРХ этого стека: стек только хранит и навигирует,
восстановление снимка (save/holder.set/publish) — ответственность контроллера.

Семантика зеркалит ``ActionBus`` (snapshot + coalescing + max_history):
  - record(): новая запись чистит redo-стек; coalescing мержит burst по совпадающему
    coalesce_key с вершиной (сохраняется before самой первой, after берётся новый).
  - take_undo(): двигает запись undo → redo, возвращает снимок ``before``.
  - take_redo(): двигает запись redo → undo, возвращает снимок ``after``.

Идентичность снимков сохраняется (возвращается тот же объект, не копия) — агрегат T
предполагается immutable (frozen), поэтому хранение ссылок безопасно.

См. docs/audits/2026-06-18_command-undo-system.md (§2/§8.3), ADR ACT-002.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Generic, TypeVar, cast

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class SnapshotEntry:
    """Проекция метаданных одной записи snapshot-стека (без самих снимков).

    Generic-аналог доменного HistoryEntry: для отображения/навигации undo/redo в UI.
    Поля: label (человекочитаемое описание), command_type (дискриминатор),
    timestamp (unix-time момента записи).
    """

    label: str
    command_type: str
    timestamp: float


@dataclass(frozen=True, slots=True)
class _Snapshot:
    """Внутренняя запись стека: снимки до/после (object — агрегат T) + метаданные."""

    before: object
    after: object
    label: str
    command_type: str
    timestamp: float
    coalesce_key: str | None


class SnapshotHistory(Generic[T]):
    """Generic snapshot-based undo/redo стек над immutable-агрегатом T.

    Строительный блок (framework) под контракт ``UndoRedoController``. Хранит снимки
    (before, after) каждой мутации; undo восстанавливает before предыдущей записи,
    redo — after. Coalescing группирует серии однотипных мутаций (например, тики
    слайдера) в одну запись по совпадающему coalesce_key с вершиной стека.
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
        before: T,
        after: T,
        label: str,
        command_type: str,
        coalesce_key: str | None = None,
    ) -> None:
        """Записать выполненную мутацию в undo-стек.

        Coalescing: если coalesce_key совпадает с вершиной undo-стека, записи сливаются —
        сохраняется before самой первой (для корректного полного отката серии), after
        берётся новый. Новая запись всегда чистит redo-стек.
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

    def take_undo(self) -> T | None:
        """Снять верхнюю запись в redo и вернуть снимок before. None если стек пуст."""
        if not self._undo:
            return None
        snap = self._undo.pop()
        self._redo.append(snap)
        return cast("T", snap.before)

    def take_redo(self) -> T | None:
        """Вернуть запись из redo обратно в undo и вернуть снимок after. None если пуст."""
        if not self._redo:
            return None
        snap = self._redo.pop()
        self._undo.append(snap)
        return cast("T", snap.after)

    # ------------------------------------------------------------------
    # Запросы
    # ------------------------------------------------------------------

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def entries(self, n: int = 20) -> list[SnapshotEntry]:
        """Последние n записей undo-стека (от старых к новым). n=0 → все записи."""
        return [
            SnapshotEntry(label=s.label, command_type=s.command_type, timestamp=s.timestamp) for s in self._undo[-n:]
        ]

    def clear(self) -> None:
        """Полностью очистить undo/redo стеки."""
        self._undo.clear()
        self._redo.clear()


__all__ = ["SnapshotHistory", "SnapshotEntry"]
