# -*- coding: utf-8 -*-
"""
adapters/tests/test_topology_repository.py — тесты для TopologyRepositoryStore.

Покрывает Task G.3 (cross-tab-architecture): store владеет topology dict и
публикует TopologyReplaced на каждую мутацию (save/set_topology). Заменил
TopologyRepositoryFromHolder + TopologyHolder + suppress_legacy_notify.

Acceptance:
- satisfies Protocol TopologyRepository (load/save).
- round-trip lossless (in-memory).
- save() и set_topology() публикуют TopologyReplaced (ровно один раз).
- .topology property отдаёт текущий dict (для TopologyBridge).
- пустой store → пустой Topology.

Refs: plans/2026-05-27_cross-tab-architecture/phase-g.md (Task G.3.1)
"""

from __future__ import annotations

from typing import Any

import pytest

from multiprocess_prototype.adapters.stores.topology_repository import TopologyRepositoryStore
from multiprocess_prototype.domain.entities.topology import Topology
from multiprocess_prototype.domain.events import TopologyReplaced
from multiprocess_prototype.domain.protocols.topology_repository import TopologyRepository
from multiprocess_prototype.domain.tests._fakes import FakeEventBus


def _make_topology_dict() -> dict[str, Any]:
    """Минимальный корректный dict для Topology с одним процессом и wire."""
    return {
        "processes": [
            {
                "process_name": "proc_a",
                "process_class": "SomeProcess",
                "plugins": [],
            }
        ],
        "wires": [
            {
                "source": "proc_a.out",
                "target": "proc_b.in",
            }
        ],
        "displays": [],
        "metadata": {},
    }


@pytest.fixture
def topology_dict() -> dict[str, Any]:
    return _make_topology_dict()


@pytest.fixture
def events() -> FakeEventBus:
    return FakeEventBus()


@pytest.fixture
def store(topology_dict: dict[str, Any], events: FakeEventBus) -> TopologyRepositoryStore:
    return TopologyRepositoryStore(topology_dict, events=events)


@pytest.fixture
def empty_store(events: FakeEventBus) -> TopologyRepositoryStore:
    return TopologyRepositoryStore(None, events=events)


# --- load ---


def test_load_returns_topology_entity(store: TopologyRepositoryStore) -> None:
    """load() возвращает frozen domain.Topology с данными из store."""
    topology = store.load()

    assert isinstance(topology, Topology)
    with pytest.raises(Exception):
        topology.processes = ()  # type: ignore[misc]

    assert len(topology.processes) == 1
    assert topology.processes[0].process_name == "proc_a"
    assert len(topology.wires) == 1
    assert topology.wires[0].source == "proc_a.out"
    assert topology.wires[0].target == "proc_b.in"


# --- save / set_topology ---


def test_save_updates_topology_property(empty_store: TopologyRepositoryStore) -> None:
    """save(topology) обновляет .topology через to_dict()."""
    topology = Topology.from_dict(_make_topology_dict())

    empty_store.save(topology)

    saved = empty_store.topology
    assert isinstance(saved, dict)
    assert any(p.get("process_name") == "proc_a" for p in saved.get("processes", []))


def test_set_topology_updates_property(empty_store: TopologyRepositoryStore) -> None:
    """set_topology(dict) (интерфейс ActionBus handlers) обновляет .topology."""
    new_topo = _make_topology_dict()
    empty_store.set_topology(new_topo)
    assert empty_store.topology is new_topo


def test_round_trip(store: TopologyRepositoryStore) -> None:
    """save(t1); t2 = load() — dict идентичен."""
    t1 = store.load()
    store.save(t1)
    t2 = store.load()
    assert t1.to_dict() == t2.to_dict()


# --- публикация TopologyReplaced ---


def test_save_publishes_topology_replaced(store: TopologyRepositoryStore, events: FakeEventBus) -> None:
    """save() публикует ровно одно TopologyReplaced."""
    store.save(store.load())

    assert len(events.published) == 1
    assert isinstance(events.published[0], TopologyReplaced)


def test_set_topology_publishes_topology_replaced(empty_store: TopologyRepositoryStore, events: FakeEventBus) -> None:
    """set_topology() публикует ровно одно TopologyReplaced (для ActionBus-мутаций)."""
    empty_store.set_topology(_make_topology_dict())

    assert len(events.published) == 1
    assert isinstance(events.published[0], TopologyReplaced)


# --- edge cases / protocol ---


def test_empty_store_load_returns_empty_topology(empty_store: TopologyRepositoryStore) -> None:
    """Пустой store (None) → load() возвращает Topology с пустыми коллекциями."""
    topology = empty_store.load()

    assert isinstance(topology, Topology)
    assert topology.processes == ()
    assert topology.wires == ()
    assert topology.displays == ()
    assert topology.metadata == {}


def test_satisfies_protocol(store: TopologyRepositoryStore) -> None:
    """TopologyRepositoryStore удовлетворяет Protocol TopologyRepository."""
    typed_repo: TopologyRepository = store  # type: ignore[assignment]

    assert callable(typed_repo.load)
    assert callable(typed_repo.save)
    assert isinstance(typed_repo.load(), Topology)
