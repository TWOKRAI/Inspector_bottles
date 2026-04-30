# multiprocess_prototype/tests/unit/test_settings_profile_combo_model.py
"""Unit-тесты profile_combo_model — from_profile_manager / sync_current / profile_id_from_model
(Phase 2, Task 2.2). Без PySide6.
"""

from __future__ import annotations

from multiprocess_prototype.frontend.widgets.recipes.recipes_widget.slot_combo_model import (
    RecipeSlotComboModel,
)
from multiprocess_prototype.frontend.widgets.recipes.settings_profile_widget.profile_combo_model import (
    from_profile_manager,
    profile_id_from_model,
    sync_current,
)

# ---------------------------------------------------------------------------
# Вспомогательные mock-объекты
# ---------------------------------------------------------------------------


class _FakeManager:
    """Мок менеджера с фиксированным списком профилей и текущим профилем."""

    def __init__(self, profiles: list[str], current: str = "default") -> None:
        self._profiles = list(profiles)
        self._current = current

    def list_profiles(self) -> list[str]:
        return list(self._profiles)

    def get_current_profile_id(self) -> str:
        return self._current


class _FakeManagerRaises:
    """Мок менеджера, бросающий исключение в list_profiles."""

    def list_profiles(self) -> list[str]:
        raise RuntimeError("broken")

    def get_current_profile_id(self) -> str:
        raise RuntimeError("broken")


# ---------------------------------------------------------------------------
# TestFromProfileManager
# ---------------------------------------------------------------------------


class TestFromProfileManager:
    def test_with_profiles(self) -> None:
        mgr = _FakeManager(["default", "fast", "prod"])
        model = from_profile_manager(mgr)
        assert model.slots == ["default", "fast", "prod"]

    def test_empty_profiles_fallback(self) -> None:
        mgr = _FakeManager([])
        model = from_profile_manager(mgr)
        assert model.slots == ["default"]

    def test_none_manager_fallback(self) -> None:
        model = from_profile_manager(None)
        assert model.slots == ["default"]

    def test_labels_are_profile_ids(self) -> None:
        """label_fn = lambda pid: pid — метки совпадают с id, без префикса 'Слот'."""
        mgr = _FakeManager(["fast"])
        model = from_profile_manager(mgr)
        assert model.labels == ["fast"]

    def test_manager_without_list_profiles_attribute_fallback(self) -> None:
        """Объект без list_profiles — fallback на ['default']."""
        model = from_profile_manager(object())
        assert model.slots == ["default"]

    def test_manager_raises_fallback(self) -> None:
        """list_profiles() бросает — fallback на ['default']."""
        model = from_profile_manager(_FakeManagerRaises())
        assert model.slots == ["default"]

    def test_slots_are_strings(self) -> None:
        """Убеждаемся, что все slot-id — строки, даже если менеджер вернул нечто иное."""
        class _IntManager:
            def list_profiles(self):
                return [1, 2, 3]

        model = from_profile_manager(_IntManager())
        assert all(isinstance(s, str) for s in model.slots)


# ---------------------------------------------------------------------------
# TestSyncCurrent
# ---------------------------------------------------------------------------


class TestSyncCurrent:
    def test_sets_correct_index(self) -> None:
        model = RecipeSlotComboModel(slots=["default", "fast", "prod"])
        mgr = _FakeManager(["default", "fast", "prod"], current="fast")
        sync_current(model, mgr)
        assert model.current_index == 1

    def test_nonexistent_current_fallback_zero(self) -> None:
        model = RecipeSlotComboModel(slots=["default", "fast"])
        mgr = _FakeManager(["default", "fast"], current="nonexistent")
        sync_current(model, mgr)
        assert model.current_index == 0

    def test_none_manager_leaves_index_unchanged(self) -> None:
        model = RecipeSlotComboModel(slots=["default"], current_index=0)
        sync_current(model, None)
        assert model.current_index == 0

    def test_manager_without_get_current_profile_id(self) -> None:
        """Объект без get_current_profile_id — ничего не меняем."""
        model = RecipeSlotComboModel(slots=["default", "fast"], current_index=1)

        class _NoMethod:
            pass

        sync_current(model, _NoMethod())
        assert model.current_index == 1

    def test_manager_raises_leaves_index_unchanged(self) -> None:
        model = RecipeSlotComboModel(slots=["default"], current_index=0)
        sync_current(model, _FakeManagerRaises())
        assert model.current_index == 0

    def test_sets_first_profile_correctly(self) -> None:
        model = RecipeSlotComboModel(slots=["alpha", "beta"])
        mgr = _FakeManager(["alpha", "beta"], current="alpha")
        sync_current(model, mgr)
        assert model.current_index == 0


# ---------------------------------------------------------------------------
# TestProfileIdFromModel
# ---------------------------------------------------------------------------


class TestProfileIdFromModel:
    def test_returns_slot_at_current_index(self) -> None:
        model = RecipeSlotComboModel(slots=["default", "fast"], current_index=1)
        assert profile_id_from_model(model) == "fast"

    def test_returns_str(self) -> None:
        model = RecipeSlotComboModel(slots=["default", "fast"], current_index=1)
        result = profile_id_from_model(model)
        assert isinstance(result, str)

    def test_returns_first_when_index_zero(self) -> None:
        model = RecipeSlotComboModel(slots=["default", "fast"], current_index=0)
        assert profile_id_from_model(model) == "default"

    def test_empty_slots_returns_empty_string(self) -> None:
        model = RecipeSlotComboModel(slots=[], current_index=0)
        assert profile_id_from_model(model) == ""
