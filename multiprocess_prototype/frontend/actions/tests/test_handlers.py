"""Тесты FieldSetHandler и RecipeApplyHandler (Phase 11)."""
from __future__ import annotations

from typing import Any

import pytest

from multiprocess_framework.modules.actions_module.schemas import Action
from multiprocess_prototype.frontend.actions.handlers.field_set_handler import FieldSetHandler
from multiprocess_prototype.frontend.actions.handlers.recipe_handler import RecipeApplyHandler
from multiprocess_prototype.frontend.topology_holder import TopologyHolder


# ---------------------------------------------------------------------------
# Вспомогательный FakeRM (заменяет RegistersManager)
# ---------------------------------------------------------------------------

class FakeRM:
    """Минимальный stub RegistersManager для тестов handlers."""

    def __init__(self) -> None:
        self._values: dict[tuple[str, str], Any] = {}

    def set_field_value(
        self,
        register_name: str,
        field_name: str,
        value: Any,
    ) -> tuple[bool, str | None]:
        self._values[(register_name, field_name)] = value
        return True, None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def rm() -> FakeRM:
    """Чистый FakeRM для каждого теста."""
    return FakeRM()


@pytest.fixture
def field_set_handler() -> FieldSetHandler:
    """Экземпляр FieldSetHandler."""
    return FieldSetHandler()


@pytest.fixture
def holder() -> TopologyHolder:
    """TopologyHolder с пустой начальной topology."""
    return TopologyHolder(initial={})


@pytest.fixture
def recipe_handler(holder: TopologyHolder) -> RecipeApplyHandler:
    """RecipeApplyHandler, привязанный к holder."""
    return RecipeApplyHandler(holder)


# ---------------------------------------------------------------------------
# Тесты FieldSetHandler
# ---------------------------------------------------------------------------

class TestFieldSetHandler:
    def test_field_set_handler_apply(self, field_set_handler: FieldSetHandler, rm: FakeRM) -> None:
        """apply устанавливает новое значение поля через rm.set_field_value."""
        action = Action(
            action_type="field_set",
            register_name="processing",
            field_name="threshold",
            forward_patch={"value": 75},
            backward_patch={"value": 50},
        )
        field_set_handler.apply(action, rm)
        assert rm._values[("processing", "threshold")] == 75

    def test_field_set_handler_revert(self, field_set_handler: FieldSetHandler, rm: FakeRM) -> None:
        """revert восстанавливает предыдущее значение (backward_patch)."""
        action = Action(
            action_type="field_set",
            register_name="source",
            field_name="brightness",
            forward_patch={"value": 200},
            backward_patch={"value": 100},
        )
        # Сначала применяем forward, потом откатываем
        field_set_handler.apply(action, rm)
        field_set_handler.revert(action, rm)
        assert rm._values[("source", "brightness")] == 100

    def test_field_set_handler_missing_names(
        self,
        field_set_handler: FieldSetHandler,
        rm: FakeRM,
    ) -> None:
        """Пустые register_name/field_name — обработчик пропускает без ошибки."""
        action_no_register = Action(
            action_type="field_set",
            register_name=None,
            field_name="threshold",
            forward_patch={"value": 10},
            backward_patch={"value": 5},
        )
        action_no_field = Action(
            action_type="field_set",
            register_name="processing",
            field_name=None,
            forward_patch={"value": 10},
            backward_patch={"value": 5},
        )
        # Не должно бросать исключений
        field_set_handler.apply(action_no_register, rm)
        field_set_handler.apply(action_no_field, rm)
        # rm не должен содержать записей — set_field_value не вызывался
        assert len(rm._values) == 0

    def test_field_set_handler_apply_correct_value_type(
        self,
        field_set_handler: FieldSetHandler,
        rm: FakeRM,
    ) -> None:
        """apply передаёт точное значение из forward_patch['value']."""
        action = Action(
            action_type="field_set",
            register_name="output",
            field_name="enabled",
            forward_patch={"value": True},
            backward_patch={"value": False},
        )
        field_set_handler.apply(action, rm)
        assert rm._values[("output", "enabled")] is True


# ---------------------------------------------------------------------------
# Тесты RecipeApplyHandler
# ---------------------------------------------------------------------------

class TestRecipeApplyHandler:
    def test_recipe_handler_apply_sets_topology(
        self,
        recipe_handler: RecipeApplyHandler,
        holder: TopologyHolder,
        rm: FakeRM,
    ) -> None:
        """apply устанавливает topology из forward_patch в TopologyHolder."""
        new_topo = {"processes": [{"name": "cam"}], "version": 2}
        action = Action(
            action_type="recipe_apply",
            forward_patch={"topology": new_topo, "recipe_name": "Setup A"},
            backward_patch={"topology": {}},
        )
        recipe_handler.apply(action, rm)
        assert holder.topology == new_topo

    def test_recipe_handler_revert_restores_topology(
        self,
        recipe_handler: RecipeApplyHandler,
        holder: TopologyHolder,
        rm: FakeRM,
    ) -> None:
        """revert восстанавливает предыдущую topology из backward_patch."""
        prev_topo = {"processes": [], "version": 1}
        new_topo = {"processes": [{"name": "proc"}], "version": 2}
        holder.set_topology(new_topo)

        action = Action(
            action_type="recipe_apply",
            forward_patch={"topology": new_topo},
            backward_patch={"topology": prev_topo},
        )
        recipe_handler.revert(action, rm)
        assert holder.topology == prev_topo

    def test_recipe_handler_apply_empty_topology_skipped(
        self,
        recipe_handler: RecipeApplyHandler,
        holder: TopologyHolder,
        rm: FakeRM,
    ) -> None:
        """apply с пустой topology в forward_patch не меняет holder."""
        old_topo = {"processes": [{"name": "unchanged"}]}
        holder.set_topology(old_topo)

        action = Action(
            action_type="recipe_apply",
            forward_patch={"topology": {}},  # пустая — должна быть пропущена
            backward_patch={"topology": old_topo},
        )
        recipe_handler.apply(action, rm)
        # topology не должна измениться
        assert holder.topology == old_topo

    def test_recipe_handler_apply_notifies_callbacks(
        self,
        recipe_handler: RecipeApplyHandler,
        holder: TopologyHolder,
        rm: FakeRM,
    ) -> None:
        """apply вызывает callbacks TopologyHolder при смене topology."""
        received: list[dict] = []
        holder.on_changed(received.append)

        new_topo = {"processes": [{"name": "p1"}]}
        action = Action(
            action_type="recipe_apply",
            forward_patch={"topology": new_topo},
            backward_patch={"topology": {}},
        )
        recipe_handler.apply(action, rm)
        assert len(received) == 1
        assert received[0] == new_topo
