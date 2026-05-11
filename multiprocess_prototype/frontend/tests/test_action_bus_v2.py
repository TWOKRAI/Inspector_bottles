"""Тесты ActionBus v2 integration (Phase 11) — undo/redo, coalescing, factory."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from multiprocess_framework.modules.actions_module.schemas import Action
from multiprocess_prototype.frontend.actions import (
    ActionBus,
    V2ActionBuilder,
    create_action_bus,
    FIELD_SET,
    RECIPE_APPLY,
)
from multiprocess_prototype.frontend.actions.action_types import FIELD_SET, RECIPE_APPLY
from multiprocess_prototype.frontend.topology_holder import TopologyHolder


# ---------------------------------------------------------------------------
# FakeRM — stub RegistersManager
# ---------------------------------------------------------------------------

class FakeRM:
    """Минимальный stub для RegistersManager."""

    def __init__(self) -> None:
        self._values: dict[tuple[str, str], Any] = {}

    def set_field_value(
        self, register_name: str, field_name: str, value: Any
    ) -> tuple[bool, str | None]:
        self._values[(register_name, field_name)] = value
        return True, None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def rm() -> FakeRM:
    """Чистый FakeRM."""
    return FakeRM()


@pytest.fixture
def holder() -> TopologyHolder:
    """TopologyHolder с пустой topology."""
    return TopologyHolder(initial={})


@pytest.fixture
def bus(rm: FakeRM, holder: TopologyHolder) -> ActionBus:
    """ActionBus v2 с обоими handlers."""
    return create_action_bus(rm, holder)


# ---------------------------------------------------------------------------
# Тесты базовых операций ActionBus
# ---------------------------------------------------------------------------

class TestActionBusBasicOps:
    def test_execute_calls_handler_apply(self, bus: ActionBus, rm: FakeRM) -> None:
        """execute вызывает handler.apply — поле устанавливается в rm."""
        action = Action(
            action_type=FIELD_SET,
            register_name="processing",
            field_name="threshold",
            forward_patch={"value": 42},
            backward_patch={"value": 0},
        )
        bus.execute(action)
        assert rm._values[("processing", "threshold")] == 42

    def test_undo_calls_handler_revert(self, bus: ActionBus, rm: FakeRM) -> None:
        """undo вызывает handler.revert — поле откатывается к backward_patch."""
        action = Action(
            action_type=FIELD_SET,
            register_name="source",
            field_name="brightness",
            forward_patch={"value": 100},
            backward_patch={"value": 50},
        )
        bus.execute(action)
        assert rm._values[("source", "brightness")] == 100

        bus.undo()
        assert rm._values[("source", "brightness")] == 50

    def test_redo_reapplies(self, bus: ActionBus, rm: FakeRM) -> None:
        """redo после undo вызывает handler.apply снова (forward_patch)."""
        action = Action(
            action_type=FIELD_SET,
            register_name="output",
            field_name="gain",
            forward_patch={"value": 200},
            backward_patch={"value": 0},
        )
        bus.execute(action)
        bus.undo()
        assert rm._values[("output", "gain")] == 0

        bus.redo()
        assert rm._values[("output", "gain")] == 200

    def test_can_undo_can_redo(self, bus: ActionBus, rm: FakeRM) -> None:
        """can_undo/can_redo корректно отражают состояние стеков."""
        assert bus.can_undo() is False
        assert bus.can_redo() is False

        action = Action(
            action_type=FIELD_SET,
            register_name="r",
            field_name="f",
            forward_patch={"value": 1},
            backward_patch={"value": 0},
        )
        bus.execute(action)
        assert bus.can_undo() is True
        assert bus.can_redo() is False

        bus.undo()
        assert bus.can_undo() is False
        assert bus.can_redo() is True

        bus.redo()
        assert bus.can_undo() is True
        assert bus.can_redo() is False


# ---------------------------------------------------------------------------
# Тест ограничения размера истории
# ---------------------------------------------------------------------------

class TestActionBusHistory:
    def test_max_history_50(self, rm: FakeRM, holder: TopologyHolder) -> None:
        """Стек undo не превышает 50 элементов при max_history=50."""
        bus = create_action_bus(rm, holder, max_history=50)

        for i in range(60):
            action = Action(
                action_type=FIELD_SET,
                register_name="reg",
                field_name=f"field_{i}",
                forward_patch={"value": i},
                backward_patch={"value": 0},
            )
            bus.execute(action)

        assert len(bus._undo_stack) == 50


# ---------------------------------------------------------------------------
# Тест recipe_apply undo восстанавливает topology
# ---------------------------------------------------------------------------

class TestRecipeApplyUndo:
    def test_recipe_apply_undo_restores_topology(
        self,
        bus: ActionBus,
        rm: FakeRM,
        holder: TopologyHolder,
    ) -> None:
        """undo recipe_apply восстанавливает предыдущую topology."""
        prev_topo = {"processes": [], "version": 1}
        new_topo = {"processes": [{"name": "cam"}], "version": 2}
        holder.set_topology(prev_topo)

        action = V2ActionBuilder.recipe_apply("Recipe X", prev_topo, new_topo)
        bus.execute(action)
        assert holder.topology == new_topo

        bus.undo()
        assert holder.topology == prev_topo

    def test_recipe_apply_redo_reapplies_topology(
        self,
        bus: ActionBus,
        rm: FakeRM,
        holder: TopologyHolder,
    ) -> None:
        """redo после undo recipe_apply повторно применяет новую topology."""
        prev_topo = {"processes": []}
        new_topo = {"processes": [{"name": "p1"}]}
        holder.set_topology(prev_topo)

        action = V2ActionBuilder.recipe_apply("Recipe Y", prev_topo, new_topo)
        bus.execute(action)
        bus.undo()
        assert holder.topology == prev_topo

        bus.redo()
        assert holder.topology == new_topo


# ---------------------------------------------------------------------------
# Тест coalescing для field_set
# ---------------------------------------------------------------------------

class TestCoalescing:
    def test_field_set_coalescing(self, bus: ActionBus, rm: FakeRM) -> None:
        """Два field_set с одинаковым coalesce_key объединяются в один action."""
        coalesce_key = "processing.threshold"

        action1 = Action(
            action_type=FIELD_SET,
            register_name="processing",
            field_name="threshold",
            forward_patch={"value": 60},
            backward_patch={"value": 50},
            coalesce_key=coalesce_key,
        )
        action2 = Action(
            action_type=FIELD_SET,
            register_name="processing",
            field_name="threshold",
            forward_patch={"value": 70},
            backward_patch={"value": 60},
            coalesce_key=coalesce_key,
        )
        bus.execute(action1)
        bus.execute(action2)

        # В стеке должна быть ровно одна запись
        assert len(bus._undo_stack) == 1

        # Merged action: forward от последнего, backward от первого
        merged = bus._undo_stack[0]
        assert merged.forward_patch["value"] == 70
        assert merged.backward_patch["value"] == 50

    def test_different_coalesce_keys_not_merged(self, bus: ActionBus, rm: FakeRM) -> None:
        """Actions с разными coalesce_key НЕ объединяются."""
        action1 = Action(
            action_type=FIELD_SET,
            register_name="processing",
            field_name="threshold",
            forward_patch={"value": 60},
            backward_patch={"value": 50},
            coalesce_key="key_A",
        )
        action2 = Action(
            action_type=FIELD_SET,
            register_name="processing",
            field_name="gain",
            forward_patch={"value": 100},
            backward_patch={"value": 0},
            coalesce_key="key_B",
        )
        bus.execute(action1)
        bus.execute(action2)

        assert len(bus._undo_stack) == 2


# ---------------------------------------------------------------------------
# Тест фабрики create_action_bus
# ---------------------------------------------------------------------------

class TestBusFactory:
    def test_bus_factory_creates_with_handlers(
        self, rm: FakeRM, holder: TopologyHolder
    ) -> None:
        """create_action_bus регистрирует handlers для field_set и recipe_apply."""
        bus = create_action_bus(rm, holder)
        assert FIELD_SET in bus._handlers
        assert RECIPE_APPLY in bus._handlers

    def test_bus_factory_default_max_history_50(
        self, rm: FakeRM, holder: TopologyHolder
    ) -> None:
        """create_action_bus устанавливает max_history=50 по умолчанию."""
        bus = create_action_bus(rm, holder)
        assert bus._max_history == 50

    def test_bus_factory_custom_max_history(
        self, rm: FakeRM, holder: TopologyHolder
    ) -> None:
        """create_action_bus принимает кастомный max_history."""
        bus = create_action_bus(rm, holder, max_history=100)
        assert bus._max_history == 100
