"""Тесты TopologyMutationHandler (Task 13.1a)."""
from __future__ import annotations

from typing import Any

import pytest

from multiprocess_framework.modules.frontend_module.actions.schemas import Action
from multiprocess_prototype.frontend.actions.handlers.topology_mutation_handler import (
    TopologyMutationHandler,
)
from multiprocess_prototype.frontend.topology_holder import TopologyHolder


# ---------------------------------------------------------------------------
# Вспомогательный MockBridge
# ---------------------------------------------------------------------------


class MockBridge:
    """Mock TopologyBridge — записывает вызовы apply_topology_diff."""

    def __init__(self) -> None:
        self.calls: list[tuple[dict, dict]] = []

    def apply_topology_diff(self, old_topo: dict, new_topo: dict) -> None:
        self.calls.append((old_topo, new_topo))


class FailingBridge:
    """Mock TopologyBridge — всегда бросает исключение."""

    def apply_topology_diff(self, old_topo: dict, new_topo: dict) -> None:
        raise RuntimeError("bridge failure")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def holder() -> TopologyHolder:
    """TopologyHolder с пустой начальной topology."""
    return TopologyHolder(initial={})


@pytest.fixture
def bridge() -> MockBridge:
    """Чистый MockBridge для каждого теста."""
    return MockBridge()


@pytest.fixture
def handler(holder: TopologyHolder) -> TopologyMutationHandler:
    """TopologyMutationHandler без bridge."""
    return TopologyMutationHandler(holder)


@pytest.fixture
def handler_with_bridge(holder: TopologyHolder, bridge: MockBridge) -> TopologyMutationHandler:
    """TopologyMutationHandler с MockBridge."""
    return TopologyMutationHandler(holder, topology_bridge=bridge)


def _make_action(
    action_type: str = "process_add",
    forward_topo: dict | None = None,
    backward_topo: dict | None = None,
) -> Action:
    """Фабрика Action для тестов мутаций topology."""
    return Action(
        action_type=action_type,
        forward_patch={"topology": forward_topo if forward_topo is not None else {}},
        backward_patch={"topology": backward_topo if backward_topo is not None else {}},
    )


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


class TestTopologyMutationHandlerApply:
    def test_apply_sets_topology(
        self,
        handler: TopologyMutationHandler,
        holder: TopologyHolder,
    ) -> None:
        """apply устанавливает topology через holder из forward_patch."""
        new_topo = {"processes": [{"id": "p1"}], "wires": []}
        action = _make_action(forward_topo=new_topo, backward_topo={})
        handler.apply(action, rm=None)
        assert holder.topology == new_topo

    def test_revert_restores_topology(
        self,
        handler: TopologyMutationHandler,
        holder: TopologyHolder,
    ) -> None:
        """revert восстанавливает topology из backward_patch."""
        prev_topo = {"processes": [], "wires": []}
        new_topo = {"processes": [{"id": "p1"}], "wires": []}
        holder.set_topology(new_topo)

        action = _make_action(forward_topo=new_topo, backward_topo=prev_topo)
        handler.revert(action, rm=None)
        assert holder.topology == prev_topo

    def test_apply_calls_bridge(
        self,
        handler_with_bridge: TopologyMutationHandler,
        holder: TopologyHolder,
        bridge: MockBridge,
    ) -> None:
        """apply вызывает bridge.apply_topology_diff(old, new)."""
        old_topo = {"processes": [], "wires": []}
        new_topo = {"processes": [{"id": "p1"}], "wires": []}
        action = _make_action(forward_topo=new_topo, backward_topo=old_topo)

        handler_with_bridge.apply(action, rm=None)

        assert len(bridge.calls) == 1
        called_old, called_new = bridge.calls[0]
        assert called_old == old_topo
        assert called_new == new_topo

    def test_revert_calls_bridge(
        self,
        handler_with_bridge: TopologyMutationHandler,
        holder: TopologyHolder,
        bridge: MockBridge,
    ) -> None:
        """revert вызывает bridge.apply_topology_diff(new, old) для undo."""
        old_topo = {"processes": [], "wires": []}
        new_topo = {"processes": [{"id": "p1"}], "wires": []}
        holder.set_topology(new_topo)
        action = _make_action(forward_topo=new_topo, backward_topo=old_topo)

        handler_with_bridge.revert(action, rm=None)

        assert len(bridge.calls) == 1
        called_old, called_new = bridge.calls[0]
        # при revert: diff от new → old
        assert called_old == new_topo
        assert called_new == old_topo

    def test_no_bridge_graceful(
        self,
        handler: TopologyMutationHandler,
        holder: TopologyHolder,
    ) -> None:
        """Без bridge apply работает корректно — только holder обновляется."""
        new_topo = {"processes": [{"id": "wire_test"}], "wires": []}
        action = _make_action(forward_topo=new_topo, backward_topo={})
        # Не должно бросать исключений
        handler.apply(action, rm=None)
        assert holder.topology == new_topo

    def test_apply_empty_topology_skipped(
        self,
        handler: TopologyMutationHandler,
        holder: TopologyHolder,
    ) -> None:
        """apply с пустой topology в forward_patch не меняет holder."""
        existing = {"processes": [{"id": "kept"}], "wires": []}
        holder.set_topology(existing)

        action = _make_action(forward_topo={}, backward_topo=existing)
        handler.apply(action, rm=None)

        # topology должна остаться прежней
        assert holder.topology == existing

    def test_revert_empty_topology_skipped(
        self,
        handler: TopologyMutationHandler,
        holder: TopologyHolder,
    ) -> None:
        """revert с пустой topology в backward_patch не меняет holder."""
        existing = {"processes": [{"id": "kept"}], "wires": []}
        holder.set_topology(existing)

        action = _make_action(forward_topo=existing, backward_topo={})
        handler.revert(action, rm=None)

        # topology должна остаться прежней
        assert holder.topology == existing

    def test_bridge_exception_graceful(
        self,
        holder: TopologyHolder,
    ) -> None:
        """Исключение в bridge не ломает apply — graceful degradation."""
        failing_bridge = FailingBridge()
        h = TopologyMutationHandler(holder, topology_bridge=failing_bridge)

        new_topo = {"processes": [{"id": "x"}], "wires": []}
        action = _make_action(forward_topo=new_topo, backward_topo={})

        # Не должно бросать исключений
        h.apply(action, rm=None)
        # holder всё равно обновился
        assert holder.topology == new_topo
