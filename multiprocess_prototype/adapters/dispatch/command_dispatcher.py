# -*- coding: utf-8 -*-
"""
adapters/dispatch/command_dispatcher.py — центральный orchestrator Phase C (Task C.6).

CommandDispatcherOrchestrator реализует Protocol CommandDispatcher из domain/protocols/:
    dispatch(command: ProjectCommand) -> list[ProjectEvent]

Алгоритм dispatch:
    1. project = holder.get()
    2. ctx = apply_context_factory() -- динамический ApplyContext (новый каждый вызов)
    3. new_project, events = project.apply(command, catalogs=ctx)
    4. topology_repo.save(new_project.topology) -- legacy callbacks вызываются (Q7)
    5. holder.set(new_project)
    6. for ev in events: event_bus.publish(ev)
    7. return events

Q7 (user-confirmed): suppress_legacy_notify НЕ используется по умолчанию.
Двойная нотификация (legacy holder.on_changed + EventBus) -- осознанный временный
компромисс на Phase D/E. Suppression активируется только в Phase F после
миграции всех подписчиков на EventBus.

Q1: Project = source of truth (ProjectHolder), TopologyHolder = derived store.

DomainError: если Project.apply() бросает DomainError, orchestrator пробрасывает
без изменений. holder и topology_repo остаются в предыдущем состоянии (implicit
rollback -- save/set не вызываются до apply).

Refs: plans/2026-05-27_cross-tab-architecture/phase-c-adapters.md (Task C.6)
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from multiprocess_prototype.domain.commands import ProjectCommand
from multiprocess_prototype.domain.entities.project import ApplyContext, Project
from multiprocess_prototype.domain.events import ProjectEvent
from multiprocess_prototype.domain.protocols import EventBusProtocol
from multiprocess_prototype.domain.protocols import TopologyRepository

logger = logging.getLogger(__name__)


class ProjectHolder:
    """Mutable wrapper над текущим (immutable) frozen Project.

    State dispatcher'а: каждый dispatch получает current Project,
    после apply() -> set новый (frozen) Project.

    Thread-safety: НЕ потокобезопасен (single-threaded GUI editor предположение).
    """

    def __init__(self, initial: Project) -> None:
        self._project: Project = initial

    def get(self) -> Project:
        """Получить текущий frozen Project."""
        return self._project

    def set(self, project: Project) -> None:
        """Заменить текущий Project на новый (frozen).

        Pre: project -- валидный frozen Project (после apply()).
        Post: get() возвращает новый project.
        """
        self._project = project


class CommandDispatcherOrchestrator:
    """Центральный orchestrator Phase C: dispatch(cmd) -> apply -> save -> publish.

    Единая точка входа для presenter'ов Phase E: отправил команду, получил
    список событий. Project.apply() остаётся чистой функцией без side effects.

    Q7 (user-confirmed): suppress_legacy_notify НЕ используется по умолчанию.
    Двойная нотификация (legacy holder.on_changed + EventBus) -- осознанный
    временный компромисс на Phase D/E. Suppression активируется только в Phase F
    после миграции всех подписчиков на EventBus.

    Q1: Project = source of truth (ProjectHolder), TopologyHolder = derived store.
    """

    def __init__(
        self,
        project_holder: ProjectHolder,
        topology_repo: TopologyRepository,
        event_bus: EventBusProtocol,
        apply_context_factory: Callable[[], ApplyContext],
    ) -> None:
        self._holder = project_holder
        self._topology_repo = topology_repo
        self._event_bus = event_bus
        self._apply_context_factory = apply_context_factory

    def dispatch(self, command: ProjectCommand) -> list[ProjectEvent]:
        """Выполнить команду: apply -> save topology -> publish events.

        Pre:
            command -- элемент ProjectCommand union.
        Post:
            - Project в holder обновлён.
            - Topology записана в topology_repo (legacy callbacks вызваны).
            - Все события опубликованы через EventBus.
            - Возвращает список опубликованных событий.
        Raises:
            DomainError -- если Project.apply() нарушает invariant.
                           holder и repo остаются неизменными.
        """
        # 1. Текущий Project
        current = self._holder.get()

        # 2. Динамический ApplyContext (новый каждый dispatch)
        ctx = self._apply_context_factory()

        # 3. Чистая функция Project.apply -- может бросить DomainError
        #    Если бросит -- steps 4-6 не выполняются (implicit rollback)
        new_project, events = current.apply(command, catalogs=ctx)

        # 4. Пишем topology в derived store (legacy callbacks вызываются -- Q7)
        self._topology_repo.save(new_project.topology)

        # 5. Обновляем Project в holder (source of truth -- Q1)
        self._holder.set(new_project)

        # 6. Публикуем каждое событие через EventBus
        for event in events:
            self._event_bus.publish(event)

        logger.debug(
            "dispatch %s -> %d event(s)",
            type(command).__name__,
            len(events),
        )

        return events
