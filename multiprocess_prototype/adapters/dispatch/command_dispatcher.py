# -*- coding: utf-8 -*-
"""
adapters/dispatch/command_dispatcher.py — центральный orchestrator Phase C (Task C.6).

CommandDispatcherOrchestrator реализует Protocol CommandDispatcher из domain/protocols/:
    dispatch(command: ProjectCommand) -> list[ProjectEvent]

Алгоритм dispatch:
    1. project = holder.get()
    2. ctx = apply_context_factory() -- динамический ApplyContext (новый каждый вызов)
    3. new_project, events = project.apply(command, catalogs=ctx)
    4. topology_repo.save(new_project.topology) -- store публикует TopologyReplaced (G.3)
    5. holder.set(new_project)
    6. for ev in events: event_bus.publish(ev)
    7. return events

G.3: topology_repo.save() публикует TopologyReplaced на тот же EventBus, что и
доменные события из шага 6. Бывший legacy holder.on_changed + suppress_legacy_notify
удалены вместе с TopologyHolder.

Q1: Project = source of truth (ProjectHolder), topology_repo = derived store.

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
from multiprocess_prototype.domain.protocols import EventBusProtocol, HistoryEntry
from multiprocess_prototype.domain.protocols import TopologyRepository

from .history import ProjectHistory
from .project_holder import ProjectHolder  # re-export для backward-compat

logger = logging.getLogger(__name__)


def _describe(command: ProjectCommand) -> str:
    """Человекочитаемый label команды для History tab (G.4.1).

    Берёт наиболее информативный атрибут команды; fallback — имя класса.
    """
    name = type(command).__name__
    for attr in ("process_name", "old_name", "slug", "node_id", "source", "reason"):
        val = getattr(command, attr, None)
        if val:
            return f"{name}: {val}"
    return name


class CommandDispatcherOrchestrator:
    """Центральный orchestrator Phase C: dispatch(cmd) -> apply -> save -> publish.

    Единая точка входа для presenter'ов Phase E: отправил команду, получил
    список событий. Project.apply() остаётся чистой функцией без side effects.

    G.3: topology_repo.save() публикует TopologyReplaced (store-publishes); бывший
    legacy holder.on_changed + suppress_legacy_notify удалены вместе с TopologyHolder.

    Q1: Project = source of truth (ProjectHolder), topology_repo = derived store.
    """

    def __init__(
        self,
        project_holder: ProjectHolder,
        topology_repo: TopologyRepository,
        event_bus: EventBusProtocol,
        apply_context_factory: Callable[[], ApplyContext],
        *,
        max_history: int = 50,
    ) -> None:
        self._holder = project_holder
        self._topology_repo = topology_repo
        self._event_bus = event_bus
        self._apply_context_factory = apply_context_factory
        # G.4.1: snapshot-based undo/redo поверх domain (замена legacy ActionBus)
        self._history = ProjectHistory(max_history=max_history)

    def dispatch(
        self,
        command: ProjectCommand,
        *,
        coalesce_key: str | None = None,
        undoable: bool = True,
    ) -> list[ProjectEvent]:
        """Выполнить команду: apply -> save topology -> publish events -> record history.

        Pre:
            command -- элемент ProjectCommand union.
            coalesce_key -- ключ группировки undo-записей (серия слайдер-тиков → одна
                            undo-запись). None — без coalescing.
            undoable -- False для команд, не попадающих в историю (например,
                        одноразовые reload). По умолчанию True.
        Post:
            - Project в holder обновлён.
            - Topology записана в topology_repo (store публикует TopologyReplaced).
            - Все события опубликованы через EventBus.
            - Команда записана в undo-историю (если undoable).
            - Возвращает список опубликованных событий.
        Raises:
            DomainError -- если Project.apply() нарушает invariant.
                           holder, repo и история остаются неизменными.
        """
        # 1. Текущий Project
        current = self._holder.get()

        # 2. Динамический ApplyContext (новый каждый dispatch)
        ctx = self._apply_context_factory()

        # 3. Чистая функция Project.apply -- может бросить DomainError
        #    Если бросит -- steps 4-7 не выполняются (implicit rollback, история не тронута)
        new_project, events = current.apply(command, catalogs=ctx)

        # 4. Пишем topology в derived store (store публикует TopologyReplaced -- G.3)
        self._topology_repo.save(new_project.topology)

        # 5. Обновляем Project в holder (source of truth -- Q1)
        self._holder.set(new_project)

        # 6. Публикуем каждое событие через EventBus
        for event in events:
            self._event_bus.publish(event)

        # 7. Записываем снимок в undo-историю (G.4.1)
        if undoable:
            self._history.record(
                before=current,
                after=new_project,
                label=_describe(command),
                command_type=type(command).__name__,
                coalesce_key=coalesce_key,
            )

        logger.debug(
            "dispatch %s -> %d event(s)",
            type(command).__name__,
            len(events),
        )

        return events

    # ------------------------------------------------------------------
    # Undo / redo (G.4.1) -- snapshot-based поверх ProjectHolder
    # ------------------------------------------------------------------

    def undo(self) -> bool:
        """Отменить последнюю команду: восстановить предыдущий снимок Project.

        Restore проходит через topology_repo.save → store публикует TopologyReplaced
        (store-publishes, G.3) → подписчики (презентеры) делают full reload.

        Returns:
            True если что-то отменено, False если undo-стек пуст.
        """
        target = self._history.take_undo()
        if target is None:
            return False
        self._restore(target)
        return True

    def redo(self) -> bool:
        """Повторить последнюю отменённую команду (восстановить снимок after).

        Returns:
            True если что-то повторено, False если redo-стек пуст.
        """
        target = self._history.take_redo()
        if target is None:
            return False
        self._restore(target)
        return True

    def can_undo(self) -> bool:
        """Есть ли команда для отмены."""
        return self._history.can_undo()

    def can_redo(self) -> bool:
        """Есть ли команда для повтора."""
        return self._history.can_redo()

    def history(self, n: int = 20) -> list[HistoryEntry]:
        """Последние n записей истории (от старых к новым)."""
        return self._history.entries(n)

    def clear_history(self) -> None:
        """Полностью очистить undo/redo историю (например, при загрузке нового проекта)."""
        self._history.clear()

    def _restore(self, project: Project) -> None:
        """Восстановить снимок Project: derived store + holder.

        Порядок (save → set) зеркалит dispatch: store.save() публикует
        TopologyReplaced синхронно; подписчики читают актуальную topology из repo.
        Granular-события (ProcessAdded/...) при undo НЕ переигрываются — TopologyReplaced
        достаточно для full reload (семантика legacy ActionBus сохранена).
        """
        self._topology_repo.save(project.topology)
        self._holder.set(project)
