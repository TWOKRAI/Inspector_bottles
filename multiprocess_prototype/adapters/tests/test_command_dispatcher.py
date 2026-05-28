# -*- coding: utf-8 -*-
"""
adapters/tests/test_command_dispatcher.py -- тесты CommandDispatcherOrchestrator (Task C.6).

Покрывает:
    1. dispatch(AddProcess) обновляет Project в holder и публикует событие
    2. DomainError при дубликате -- holder/repo неизменны (rollback semantic)
    3. После dispatch topology_repo.load() отражает новое состояние
    4. Legacy holder.on_changed callback вызывается при dispatch (Q7 -- двойная нотификация)
    5. Порядок публикации событий сохраняется
    6. RemoveProcess с cascade -- все события опубликованы
    7. apply_context_factory вызывается на каждом dispatch (динамический контекст)
    8. CommandDispatcherOrchestrator satisfies Protocol CommandDispatcher
    9. ProjectHolder get/set базовый тест

Refs: plans/2026-05-27_cross-tab-architecture/phase-c-adapters.md (Task C.6)
"""

from __future__ import annotations

from typing import Any

import pytest

from multiprocess_prototype.adapters.dispatch.command_dispatcher import (
    CommandDispatcherOrchestrator,
    ProjectHolder,
)
from multiprocess_prototype.domain.commands import (
    AddProcess,
    RemoveProcess,
)
from multiprocess_prototype.domain.entities.project import ApplyContext, Project
from multiprocess_prototype.domain.entities.topology import Topology
from multiprocess_prototype.domain.errors import DomainError
from multiprocess_prototype.domain.event_bus import EventBus
from multiprocess_prototype.domain.events import (
    DisplayUnbound,
    ProcessAdded,
    ProcessRemoved,
    ProjectEvent,
    WireDisconnected,
)
from multiprocess_prototype.domain.protocols.command_dispatcher import CommandDispatcher
from multiprocess_prototype.domain.tests._fakes import FakeTopologyRepository


# ---------------------------------------------------------------------------
# Вспомогательные фикстуры
# ---------------------------------------------------------------------------


def _empty_topology() -> Topology:
    """Пустая topology для начального Project."""
    return Topology()


def _make_project(**overrides: Any) -> Project:
    """Создать Project с пустой или переопределённой topology."""
    defaults: dict[str, Any] = {
        "topology": _empty_topology(),
    }
    defaults.update(overrides)
    return Project(**defaults)


def _default_ctx_factory() -> ApplyContext:
    """Factory возвращающая ApplyContext без каталогов (все invariants пропускаются)."""
    return ApplyContext()


@pytest.fixture
def project() -> Project:
    """Начальный пустой Project."""
    return _make_project()


@pytest.fixture
def holder(project: Project) -> ProjectHolder:
    """ProjectHolder с начальным Project."""
    return ProjectHolder(initial=project)


@pytest.fixture
def fake_repo() -> FakeTopologyRepository:
    """FakeTopologyRepository (in-memory)."""
    return FakeTopologyRepository()


@pytest.fixture
def event_bus() -> EventBus:
    """Реальный EventBus (для проверки publish + subscribe)."""
    return EventBus()


@pytest.fixture
def dispatcher(
    holder: ProjectHolder,
    fake_repo: FakeTopologyRepository,
    event_bus: EventBus,
) -> CommandDispatcherOrchestrator:
    """CommandDispatcherOrchestrator с default ctx factory."""
    return CommandDispatcherOrchestrator(
        project_holder=holder,
        topology_repo=fake_repo,
        event_bus=event_bus,
        apply_context_factory=_default_ctx_factory,
    )


# ---------------------------------------------------------------------------
# Тест 1: dispatch(AddProcess) обновляет Project и публикует событие
# ---------------------------------------------------------------------------


def test_dispatch_add_process_updates_project_and_publishes_event(
    dispatcher: CommandDispatcherOrchestrator,
    holder: ProjectHolder,
    event_bus: EventBus,
) -> None:
    """dispatch(AddProcess) -> events содержит ProcessAdded, holder обновлён."""
    # Подписываемся для сбора событий
    published: list[ProjectEvent] = []
    event_bus.subscribe(ProcessAdded, lambda ev: published.append(ev))

    cmd = AddProcess(process_name="camera")
    events = dispatcher.dispatch(cmd)

    # events содержит ProcessAdded
    assert len(events) == 1
    assert isinstance(events[0], ProcessAdded)
    assert events[0].process_name == "camera"

    # holder обновлён -- Project содержит процесс
    updated = holder.get()
    assert updated.topology.find_process("camera") is not None

    # EventBus получил событие
    assert len(published) == 1
    assert published[0].process_name == "camera"


# ---------------------------------------------------------------------------
# Тест 2: DomainError при дубликате -- holder/repo неизменны
# ---------------------------------------------------------------------------


def test_dispatch_propagates_domain_error(
    dispatcher: CommandDispatcherOrchestrator,
    holder: ProjectHolder,
    fake_repo: FakeTopologyRepository,
) -> None:
    """AddProcess с дубликатом имени -> DomainError, holder/repo не меняются."""
    # Добавляем процесс
    dispatcher.dispatch(AddProcess(process_name="proc1"))
    project_after_first = holder.get()
    repo_state_after_first = fake_repo.load().to_dict()

    # Попытка добавить дубликат -- DomainError
    with pytest.raises(DomainError, match="proc1"):
        dispatcher.dispatch(AddProcess(process_name="proc1"))

    # holder не изменился (остался Project после первого dispatch)
    assert holder.get() is project_after_first

    # repo не изменился
    assert fake_repo.load().to_dict() == repo_state_after_first


# ---------------------------------------------------------------------------
# Тест 3: после dispatch repo.load() отражает новое состояние
# ---------------------------------------------------------------------------


def test_dispatch_save_to_topology_repo(
    dispatcher: CommandDispatcherOrchestrator,
    fake_repo: FakeTopologyRepository,
) -> None:
    """После dispatch topology_repo содержит обновлённую topology."""
    dispatcher.dispatch(AddProcess(process_name="detector"))

    saved = fake_repo.load()
    assert saved.find_process("detector") is not None


# ---------------------------------------------------------------------------
# Тест 4: legacy holder.on_changed callback вызывается (Q7)
# ---------------------------------------------------------------------------


def test_dispatch_publishes_topology_replaced_too() -> None:
    """dispatch -> topology_repo.save() публикует TopologyReplaced (G.3: store-publishes).

    Используем реальный TopologyRepositoryStore: store.save() публикует TopologyReplaced
    на тот же EventBus, что и доменные команды (ProcessAdded). Бывший legacy
    holder.on_changed удалён в G.3.
    """
    from multiprocess_prototype.adapters.stores.topology_repository import (
        TopologyRepositoryStore,
    )
    from multiprocess_prototype.domain.events import TopologyReplaced

    # Начальный Project
    project = _make_project()
    holder = ProjectHolder(initial=project)

    # EventBus — общий для store и dispatcher
    bus = EventBus()
    process_added: list[ProjectEvent] = []
    topo_replaced: list[ProjectEvent] = []
    bus.subscribe(ProcessAdded, lambda ev: process_added.append(ev))
    bus.subscribe(TopologyReplaced, lambda ev: topo_replaced.append(ev))

    # Реальный store публикует TopologyReplaced на этот же bus
    store = TopologyRepositoryStore(project.topology.to_dict(), events=bus)

    dispatcher = CommandDispatcherOrchestrator(
        project_holder=holder,
        topology_repo=store,
        event_bus=bus,
        apply_context_factory=_default_ctx_factory,
    )

    dispatcher.dispatch(AddProcess(process_name="worker"))

    # store.save() опубликовал TopologyReplaced
    assert len(topo_replaced) == 1
    assert isinstance(topo_replaced[0], TopologyReplaced)
    # Новый процесс в store.topology
    proc_names = [p.get("process_name") for p in store.topology.get("processes", [])]
    assert "worker" in proc_names

    # Dispatcher также опубликовал доменное событие ProcessAdded
    assert len(process_added) == 1
    assert process_added[0].process_name == "worker"


# ---------------------------------------------------------------------------
# Тест 5: порядок публикации событий сохраняется
# ---------------------------------------------------------------------------


def test_dispatch_publish_order(
    holder: ProjectHolder,
    event_bus: EventBus,
    fake_repo: FakeTopologyRepository,
) -> None:
    """Несколько событий от одного dispatch -> порядок сохраняется."""
    # Создаём topology с двумя процессами и wire между ними
    topo = Topology.from_dict(
        {
            "processes": [
                {"process_name": "src", "plugins": []},
                {"process_name": "dst", "plugins": []},
            ],
            "wires": [{"source": "src", "target": "dst"}],
            "displays": [],
        }
    )
    project = _make_project(topology=topo)
    holder_local = ProjectHolder(initial=project)

    # Собираем ВСЕ события
    all_events: list[ProjectEvent] = []
    event_bus.subscribe(ProcessRemoved, lambda ev: all_events.append(ev))
    event_bus.subscribe(WireDisconnected, lambda ev: all_events.append(ev))

    dispatcher = CommandDispatcherOrchestrator(
        project_holder=holder_local,
        topology_repo=fake_repo,
        event_bus=event_bus,
        apply_context_factory=_default_ctx_factory,
    )

    events = dispatcher.dispatch(RemoveProcess(process_name="src"))

    # Порядок: ProcessRemoved -> WireDisconnected
    assert len(events) >= 2
    assert isinstance(events[0], ProcessRemoved)
    assert isinstance(events[1], WireDisconnected)

    # EventBus получил в том же порядке
    assert len(all_events) >= 2
    assert isinstance(all_events[0], ProcessRemoved)
    assert isinstance(all_events[1], WireDisconnected)


# ---------------------------------------------------------------------------
# Тест 6: RemoveProcess с cascade -- все события опубликованы
# ---------------------------------------------------------------------------


def test_dispatch_remove_process_cascade_events_published(
    event_bus: EventBus,
    fake_repo: FakeTopologyRepository,
) -> None:
    """RemoveProcess процесса с wire'ами и display binding -> все события опубликованы."""
    from multiprocess_prototype.domain.entities.display import DisplayInstance
    from multiprocess_prototype.domain.entities.wire import Wire

    topo = Topology(
        processes=(
            # Два процесса: cam и proc
            # cam будет удалён -> cascade на wire + display
            __import__("multiprocess_prototype.domain.entities.process", fromlist=["Process"]).Process(
                process_name="cam", plugins=()
            ),
            __import__("multiprocess_prototype.domain.entities.process", fromlist=["Process"]).Process(
                process_name="proc", plugins=()
            ),
        ),
        wires=(
            Wire(source="cam.out", target="proc.in"),
            Wire(source="proc.out", target="cam.in"),
        ),
        displays=(DisplayInstance(node_id="cam.preview", display_id="lcd1"),),
    )
    project = _make_project(topology=topo)
    holder_local = ProjectHolder(initial=project)

    # Собираем все типы событий
    all_events: list[ProjectEvent] = []
    for evt_type in (ProcessRemoved, WireDisconnected, DisplayUnbound):
        event_bus.subscribe(evt_type, lambda ev: all_events.append(ev))

    dispatcher = CommandDispatcherOrchestrator(
        project_holder=holder_local,
        topology_repo=fake_repo,
        event_bus=event_bus,
        apply_context_factory=_default_ctx_factory,
    )

    events = dispatcher.dispatch(RemoveProcess(process_name="cam"))

    # Ожидаем: ProcessRemoved(cam) + 2x WireDisconnected + 1x DisplayUnbound
    assert any(isinstance(ev, ProcessRemoved) and ev.process_name == "cam" for ev in events)

    wire_disconnected = [ev for ev in events if isinstance(ev, WireDisconnected)]
    assert len(wire_disconnected) == 2

    display_unbound = [ev for ev in events if isinstance(ev, DisplayUnbound)]
    assert len(display_unbound) == 1
    assert display_unbound[0].node_id == "cam.preview"

    # EventBus получил все события
    assert len(all_events) == len(events)


# ---------------------------------------------------------------------------
# Тест 7: apply_context_factory вызывается на каждом dispatch
# ---------------------------------------------------------------------------


def test_apply_context_factory_called_on_each_dispatch(
    holder: ProjectHolder,
    fake_repo: FakeTopologyRepository,
    event_bus: EventBus,
) -> None:
    """Factory вызывается на каждом dispatch (динамический контекст). Counter в fake."""
    call_count = 0

    def counting_factory() -> ApplyContext:
        nonlocal call_count
        call_count += 1
        return ApplyContext()

    dispatcher = CommandDispatcherOrchestrator(
        project_holder=holder,
        topology_repo=fake_repo,
        event_bus=event_bus,
        apply_context_factory=counting_factory,
    )

    dispatcher.dispatch(AddProcess(process_name="a"))
    dispatcher.dispatch(AddProcess(process_name="b"))
    dispatcher.dispatch(AddProcess(process_name="c"))

    assert call_count == 3


# ---------------------------------------------------------------------------
# Тест 8: satisfies Protocol CommandDispatcher
# ---------------------------------------------------------------------------


def test_satisfies_protocol(dispatcher: CommandDispatcherOrchestrator) -> None:
    """CommandDispatcherOrchestrator удовлетворяет Protocol CommandDispatcher."""
    # Структурная проверка: assignment к Protocol-типизированной переменной
    typed: CommandDispatcher = dispatcher  # noqa: F841

    # Метод dispatch callable
    assert callable(typed.dispatch)

    # Функциональная проверка: dispatch возвращает list[ProjectEvent]
    result = typed.dispatch(AddProcess(process_name="test_proto"))
    assert isinstance(result, list)
    assert len(result) > 0
    assert isinstance(result[0], ProcessAdded)


# ---------------------------------------------------------------------------
# Тест 9: ProjectHolder get/set базовый
# ---------------------------------------------------------------------------


def test_project_holder_get_set() -> None:
    """ProjectHolder.get() возвращает текущий, set() заменяет."""
    p1 = _make_project()
    holder = ProjectHolder(initial=p1)

    assert holder.get() is p1

    p2 = _make_project()
    holder.set(p2)

    assert holder.get() is p2
    assert holder.get() is not p1


# ---------------------------------------------------------------------------
# Тест 10: два последовательных dispatch -- state аккумулируется
# ---------------------------------------------------------------------------


def test_dispatch_sequential_accumulates_state(
    dispatcher: CommandDispatcherOrchestrator,
    holder: ProjectHolder,
) -> None:
    """Два AddProcess подряд -- оба процесса в итоговом Project."""
    dispatcher.dispatch(AddProcess(process_name="alpha"))
    dispatcher.dispatch(AddProcess(process_name="beta"))

    final = holder.get()
    assert final.topology.find_process("alpha") is not None
    assert final.topology.find_process("beta") is not None
    assert len(final.topology.processes) == 2
