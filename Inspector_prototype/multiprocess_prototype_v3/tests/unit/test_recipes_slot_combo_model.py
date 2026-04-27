# multiprocess_prototype_v3/tests/unit/test_recipes_slot_combo_model.py
"""Unit-тесты `RecipeSlotComboModel` — модель списка слотов для ComboBox (Phase 1, Task 1.1)."""

from __future__ import annotations

from multiprocess_prototype_v3.frontend.widgets.recipes.recipes_widget.slot_combo_model import (
    RecipeSlotComboModel,
)


class _FakeManager:
    def __init__(self, slots):
        self._slots = list(slots)

    def list_slots(self):
        return list(self._slots)


class _FakeManagerRaising:
    def list_slots(self):
        raise RuntimeError("broken")


class TestFromManager:
    def test_auto_range_when_manager_none(self) -> None:
        m = RecipeSlotComboModel.from_manager(None, 0, 5)
        assert m.slots == ["0", "1", "2", "3", "4", "5"]

    def test_uses_manager_list_slots_when_available(self) -> None:
        m = RecipeSlotComboModel.from_manager(_FakeManager(["A", "B", "C"]), 0, 5)
        assert m.slots == ["A", "B", "C"]

    def test_falls_back_to_range_when_manager_returns_empty(self) -> None:
        m = RecipeSlotComboModel.from_manager(_FakeManager([]), 1, 3)
        assert m.slots == ["1", "2", "3"]

    def test_falls_back_to_range_when_manager_raises(self) -> None:
        m = RecipeSlotComboModel.from_manager(_FakeManagerRaising(), 0, 2)
        assert m.slots == ["0", "1", "2"]

    def test_manager_without_list_slots_method(self) -> None:
        m = RecipeSlotComboModel.from_manager(object(), 0, 2)
        assert m.slots == ["0", "1", "2"]

    def test_reversed_range_normalized(self) -> None:
        m = RecipeSlotComboModel.from_manager(None, 5, 0)
        assert m.slots == ["0", "1", "2", "3", "4", "5"]


class TestIndexConversion:
    def test_index_for_existing_slot(self) -> None:
        m = RecipeSlotComboModel(slots=["A", "B", "C"])
        assert m.index_for_slot_id("B") == 1

    def test_index_for_missing_slot_returns_zero(self) -> None:
        m = RecipeSlotComboModel(slots=["A", "B"])
        assert m.index_for_slot_id("X") == 0

    def test_slot_id_for_valid_index(self) -> None:
        m = RecipeSlotComboModel(slots=["A", "B", "C"])
        assert m.slot_id_for_index(2) == "C"

    def test_slot_id_for_out_of_bounds_fallbacks_to_first(self) -> None:
        m = RecipeSlotComboModel(slots=["A", "B"])
        assert m.slot_id_for_index(999) == "A"
        assert m.slot_id_for_index(-1) == "A"

    def test_slot_id_for_empty_model(self) -> None:
        m = RecipeSlotComboModel(slots=[])
        assert m.slot_id_for_index(0) == ""
        assert m.is_empty() is True

    def test_current_slot_id_uses_current_index(self) -> None:
        m = RecipeSlotComboModel(slots=["A", "B", "C"], current_index=1)
        assert m.current_slot_id() == "B"


class TestLabels:
    def test_default_labels_with_ru_prefix(self) -> None:
        m = RecipeSlotComboModel(slots=["0", "1"])
        assert m.labels == ["Слот 0", "Слот 1"]

    def test_custom_label_fn(self) -> None:
        m = RecipeSlotComboModel(slots=["A", "B"], label_fn=lambda s: f"Recipe-{s}")
        assert m.labels == ["Recipe-A", "Recipe-B"]
