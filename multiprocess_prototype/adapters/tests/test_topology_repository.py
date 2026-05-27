# -*- coding: utf-8 -*-
"""
adapters/tests/test_topology_repository.py — тесты для TopologyRepositoryFromHolder.

Покрывает: Task C.3 Phase C (bidirectional bridge domain.Topology <-> TopologyHolder).

Acceptance criteria:
- Adapter satisfies Protocol TopologyRepository.
- Round-trip lossless (in-memory).
- Legacy holder.on_changed callback продолжает работать по умолчанию.
- suppress_legacy_notify() cm подавляет callbacks внутри блока, восстанавливает после.
- Edge case: пустой holder → пустой Topology.

Refs: plans/2026-05-27_cross-tab-architecture/phase-c-adapters.md (Task C.3)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from multiprocess_prototype.adapters.stores.topology_repository import TopologyRepositoryFromHolder
from multiprocess_prototype.domain.entities.topology import Topology
from multiprocess_prototype.domain.protocols.topology_repository import TopologyRepository
from multiprocess_prototype.frontend.topology_holder import TopologyHolder


# ---------------------------------------------------------------------------
# Вспомогательные фикстуры
# ---------------------------------------------------------------------------


def _make_topology_dict() -> dict[str, Any]:
    """Возвращает минимальный корректный dict для Topology с одним процессом и wire."""
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
    """Корректный topology dict для тестов."""
    return _make_topology_dict()


@pytest.fixture
def holder(topology_dict: dict[str, Any]) -> TopologyHolder:
    """TopologyHolder с начальной topology."""
    return TopologyHolder(initial=topology_dict)


@pytest.fixture
def repo(holder: TopologyHolder) -> TopologyRepositoryFromHolder:
    """Adapter поверх holder."""
    return TopologyRepositoryFromHolder(holder=holder)


@pytest.fixture
def empty_holder() -> TopologyHolder:
    """Пустой holder без начальных данных."""
    return TopologyHolder()


@pytest.fixture
def empty_repo(empty_holder: TopologyHolder) -> TopologyRepositoryFromHolder:
    """Adapter поверх пустого holder."""
    return TopologyRepositoryFromHolder(holder=empty_holder)


# ---------------------------------------------------------------------------
# Тест 1: load() возвращает Topology entity с правильными полями
# ---------------------------------------------------------------------------


def test_load_returns_topology_entity(holder: TopologyHolder, repo: TopologyRepositoryFromHolder) -> None:
    """load() возвращает frozen domain.Topology с данными из holder."""
    topology = repo.load()

    assert isinstance(topology, Topology)
    # Topology frozen — попытка присвоить поле должна падать
    with pytest.raises(Exception):  # pydantic frozen raises ValidationError или AttributeError
        topology.processes = ()  # type: ignore[misc]

    # Проверяем что процесс присутствует
    assert len(topology.processes) == 1
    assert topology.processes[0].process_name == "proc_a"

    # Wire присутствует
    assert len(topology.wires) == 1
    assert topology.wires[0].source == "proc_a.out"
    assert topology.wires[0].target == "proc_b.in"


# ---------------------------------------------------------------------------
# Тест 2: save() пишет в holder
# ---------------------------------------------------------------------------


def test_save_writes_to_holder(empty_holder: TopologyHolder, empty_repo: TopologyRepositoryFromHolder) -> None:
    """save(topology) обновляет holder.topology через to_dict()."""
    topology = Topology.from_dict(_make_topology_dict())

    empty_repo.save(topology)

    saved = empty_holder.topology
    assert isinstance(saved, dict)
    # Процесс должен быть в сохранённом dict
    assert any(p.get("process_name") == "proc_a" for p in saved.get("processes", []))


# ---------------------------------------------------------------------------
# Тест 3: round-trip lossless
# ---------------------------------------------------------------------------


def test_round_trip(repo: TopologyRepositoryFromHolder) -> None:
    """save(t1); t2 = load() — сравнение dict идентично."""
    t1 = repo.load()

    repo.save(t1)
    t2 = repo.load()

    # Сравниваем через dict (Topology frozen, поля одинаковы)
    assert t1.to_dict() == t2.to_dict()


# ---------------------------------------------------------------------------
# Тест 4: legacy on_changed callback вызывается при save()
# ---------------------------------------------------------------------------


def test_holder_callback_fires_on_save(
    holder: TopologyHolder,
    repo: TopologyRepositoryFromHolder,
) -> None:
    """holder.on_changed(cb) — cb вызывается при repo.save() с правильным dict."""
    cb = MagicMock()
    holder.on_changed(cb)

    topology = repo.load()
    repo.save(topology)

    cb.assert_called_once()
    # Аргумент — dict с нашими данными
    call_arg = cb.call_args[0][0]
    assert isinstance(call_arg, dict)
    assert any(p.get("process_name") == "proc_a" for p in call_arg.get("processes", []))


# ---------------------------------------------------------------------------
# Тест 5: suppress_legacy_notify() подавляет callbacks внутри блока
# ---------------------------------------------------------------------------


def test_suppress_legacy_notify_suppresses_callback(
    holder: TopologyHolder,
    repo: TopologyRepositoryFromHolder,
) -> None:
    """Внутри suppress_legacy_notify() — cb не вызывается; вне cm — вызывается."""
    cb = MagicMock()
    holder.on_changed(cb)

    topology = repo.load()

    # Внутри cm — callback НЕ должен вызываться
    with repo.suppress_legacy_notify():
        repo.save(topology)

    cb.assert_not_called()

    # После выхода из cm — callback ДОЛЖЕН вызываться снова
    repo.save(topology)
    cb.assert_called_once()


# ---------------------------------------------------------------------------
# Тест 6: пустой holder → пустой Topology
# ---------------------------------------------------------------------------


def test_empty_holder_load_returns_empty_topology(empty_repo: TopologyRepositoryFromHolder) -> None:
    """Пустой holder ({}) → load() возвращает Topology с пустыми коллекциями."""
    topology = empty_repo.load()

    assert isinstance(topology, Topology)
    assert topology.processes == ()
    assert topology.wires == ()
    assert topology.displays == ()
    assert topology.metadata == {}


# ---------------------------------------------------------------------------
# Тест 7: Protocol-совместимость (assignment check)
# ---------------------------------------------------------------------------


def test_satisfies_protocol(repo: TopologyRepositoryFromHolder) -> None:
    """TopologyRepositoryFromHolder удовлетворяет Protocol TopologyRepository."""
    # Структурная проверка: assignment к Protocol-типизированной переменной
    typed_repo: TopologyRepository = repo  # type: ignore[assignment] — проверяет наличие методов

    # Убеждаемся что методы callable
    assert callable(typed_repo.load)
    assert callable(typed_repo.save)

    # Функциональная проверка через Protocol
    result = typed_repo.load()
    assert isinstance(result, Topology)


# ---------------------------------------------------------------------------
# Тест 8: _suppress_notify сбрасывается после исключения внутри cm
# ---------------------------------------------------------------------------


def test_suppress_notify_restored_after_exception(
    holder: TopologyHolder,
    repo: TopologyRepositoryFromHolder,
) -> None:
    """_suppress_notify = False восстанавливается даже при исключении внутри cm."""
    cb = MagicMock()
    holder.on_changed(cb)
    topology = repo.load()

    with pytest.raises(RuntimeError):
        with repo.suppress_legacy_notify():
            raise RuntimeError("симуляция ошибки внутри cm")

    # После исключения suppress должен быть снят
    assert holder._suppress_notify is False

    # И callbacks должны снова работать
    repo.save(topology)
    cb.assert_called_once()
