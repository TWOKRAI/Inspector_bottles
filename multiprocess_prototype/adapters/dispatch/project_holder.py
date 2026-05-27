# -*- coding: utf-8 -*-
"""
adapters/dispatch/project_holder.py — thread-safe mutable wrapper над текущим Project.

ProjectHolder — «тупой» state-контейнер: только get/set с RLock-защитой.
Granular events публикует CommandDispatcherOrchestrator (он знает, какие
domain-events вернула Project.apply()).

Решение Q2 (Phase D decisions): holder НЕ публикует event'ы.
RLock (re-entrant) — чтобы при get() внутри set() callback'е не было deadlock.

Refs: plans/2026-05-27_cross-tab-architecture/phase-d-app-services.md (Task D.3)
"""

from __future__ import annotations

from threading import RLock

from multiprocess_prototype.domain.entities.project import Project


class ProjectHolder:
    """Thread-safe mutable wrapper над текущим (immutable) frozen Project.

    Тупой holder без publish-семантики. События публикует CommandDispatcher
    (он знает, какие event'ы вернула Project.apply()).

    Lock: RLock (re-entrant) — безопасен при вложенных вызовах get() внутри
    set()-callback'ов. Не будет deadlock при таком паттерне использования.
    """

    def __init__(self, initial: Project) -> None:
        self._current: Project = initial
        self._lock: RLock = RLock()

    def get(self) -> Project:
        """Получить текущий frozen Project (thread-safe)."""
        with self._lock:
            return self._current

    def set(self, project: Project) -> None:
        """Заменить текущий Project на новый frozen Project (thread-safe).

        Pre: project — валидный frozen Project (после apply()).
        Post: get() возвращает новый project.
        """
        with self._lock:
            self._current = project
