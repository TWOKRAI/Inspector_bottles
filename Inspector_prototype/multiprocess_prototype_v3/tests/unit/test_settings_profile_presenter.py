# multiprocess_prototype_v3/tests/unit/test_settings_profile_presenter.py
"""Unit-тесты SettingsProfilePresenter — логика без Qt (Phase 2, Task 2.3).

Проверяет on_apply_clicked, on_save_clicked, on_default_clicked, on_leaf_value_changed
без каких-либо зависимостей от PyQt5.
"""

from __future__ import annotations

from typing import Any

import pytest

from multiprocess_prototype_v3.frontend.managers.settings_profile_manager import ShmBudgetError
from multiprocess_prototype_v3.frontend.widgets.recipes_widget.slot_combo_model import (
    RecipeSlotComboModel,
)
from multiprocess_prototype_v3.frontend.widgets.settings_profile_widget.model import (
    SettingsProfileModel,
)
from multiprocess_prototype_v3.frontend.widgets.settings_profile_widget.presenter import (
    SettingsProfilePresenter,
)
from multiprocess_prototype_v3.frontend.widgets.settings_profile_widget.schemas import (
    SettingsProfileTabConfig,
)

# ---------------------------------------------------------------------------
# Mock-объекты
# ---------------------------------------------------------------------------


class FakeView:
    """Реализует SettingsProfilePanelViewProtocol без PyQt5."""

    def __init__(self, current_id: str = "default") -> None:
        self._current_id = current_id
        self.refresh_calls: int = 0
        self.errors: list[str] = []
        self.leaf_texts: dict[tuple[str, str], str] = {}

    def current_profile_id(self) -> str:
        return self._current_id

    def refresh_table_rows(self) -> None:
        self.refresh_calls += 1

    def set_leaf_value_text(self, group_id: str, field_id: str, text: str) -> None:
        self.leaf_texts[(group_id, field_id)] = text

    def show_error(self, message: str) -> None:
        self.errors.append(message)


class FakeProfileManager:
    """Минимальный mock SettingsProfileManagerProtocol."""

    def __init__(
        self,
        profiles: dict[str, dict] | None = None,
        raise_on_switch: Exception | None = None,
    ) -> None:
        self.profiles = dict(profiles or {})
        self.current = "default"
        self._raise_on_switch = raise_on_switch
        self.switch_calls: list[str] = []
        self.save_calls: list[tuple[str, dict]] = []

    def list_profiles(self) -> list[str]:
        return list(self.profiles.keys())

    def get_current_profile_id(self) -> str:
        return self.current

    def switch_profile(self, profile_id: str, registers_bridge: Any) -> bool:
        self.switch_calls.append(profile_id)
        if self._raise_on_switch is not None:
            raise self._raise_on_switch
        self.current = profile_id
        return True

    def save_profile_snapshot(self, profile_id: str, snapshot: dict) -> bool:
        self.save_calls.append((profile_id, snapshot))
        return True


class FakeRegister:
    """Простой регистр с данными."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = dict(data)

    def model_dump(self) -> dict[str, Any]:
        return dict(self._data)

    def get_field_meta(self, field_name: str) -> None:
        return None


class FakeRM:
    """Минимальный mock RegistersManager."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self._data: dict[str, Any] = data or {
            "camera_count": 1,
            "ring_buffer_size": 3,
            "shm_budget_mb": 512,
        }
        self._set_calls: list[tuple[str, str, Any]] = []

    def get_register(self, name: str) -> FakeRegister | None:
        if name != "settings":
            return None
        return FakeRegister(self._data)

    def model_dump_all(self) -> dict[str, Any]:
        return {"settings": dict(self._data)}

    def set_field_value(
        self, register_name: str, field_name: str, value: Any
    ) -> tuple[bool, str | None]:
        self._set_calls.append((register_name, field_name, value))
        if register_name == "settings" and field_name in self._data:
            self._data[field_name] = value
            return (True, None)
        return (False, "unknown field")

    def get_field_metadata(self, register_name: str, field_name: str) -> dict:
        return {}

    def model_validate_all(self, data: dict[str, Any], strict: bool = False) -> None:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def ui() -> SettingsProfileTabConfig:
    return SettingsProfileTabConfig()


@pytest.fixture()
def rm() -> FakeRM:
    return FakeRM()


@pytest.fixture()
def profile_manager() -> FakeProfileManager:
    return FakeProfileManager(profiles={"default": {}, "fast": {}, "prod": {}})


@pytest.fixture()
def view() -> FakeView:
    return FakeView(current_id="fast")


@pytest.fixture()
def combo_model() -> RecipeSlotComboModel:
    return RecipeSlotComboModel(slots=["default", "fast", "prod"], current_index=1)


@pytest.fixture()
def model(
    rm: FakeRM,
    profile_manager: FakeProfileManager,
    combo_model: RecipeSlotComboModel,
    ui: SettingsProfileTabConfig,
) -> SettingsProfileModel:
    return SettingsProfileModel(
        ui=ui,
        profile_manager=profile_manager,
        rm=rm,
        combo_model=combo_model,
    )


@pytest.fixture()
def presenter(view: FakeView, model: SettingsProfileModel) -> SettingsProfilePresenter:
    return SettingsProfilePresenter(view=view, model=model)


# ---------------------------------------------------------------------------
# TestOnApplyClicked
# ---------------------------------------------------------------------------


class TestOnApplyClicked:
    def test_success_calls_switch_profile_with_correct_id(
        self,
        presenter: SettingsProfilePresenter,
        profile_manager: FakeProfileManager,
        view: FakeView,
    ) -> None:
        result = presenter.on_apply_clicked()
        assert result is True
        assert "fast" in profile_manager.switch_calls

    def test_success_calls_refresh_table_rows(
        self,
        presenter: SettingsProfilePresenter,
        view: FakeView,
    ) -> None:
        presenter.on_apply_clicked()
        assert view.refresh_calls == 1

    def test_shm_budget_error_calls_show_error(
        self,
        rm: FakeRM,
        combo_model: RecipeSlotComboModel,
        ui: SettingsProfileTabConfig,
        view: FakeView,
    ) -> None:
        err = ShmBudgetError(
            camera_count=8,
            ring_buffer_size=3,
            required_mb=600.0,
            budget_mb=64,
        )
        pm = FakeProfileManager(profiles={"fast": {}}, raise_on_switch=err)
        m = SettingsProfileModel(ui=ui, profile_manager=pm, rm=rm, combo_model=combo_model)
        p = SettingsProfilePresenter(view=view, model=m)
        result = p.on_apply_clicked()
        assert result is False
        assert len(view.errors) == 1

    def test_shm_budget_error_does_not_propagate(
        self,
        rm: FakeRM,
        combo_model: RecipeSlotComboModel,
        ui: SettingsProfileTabConfig,
        view: FakeView,
    ) -> None:
        err = ShmBudgetError(
            camera_count=8,
            ring_buffer_size=3,
            required_mb=600.0,
            budget_mb=64,
        )
        pm = FakeProfileManager(profiles={"fast": {}}, raise_on_switch=err)
        m = SettingsProfileModel(ui=ui, profile_manager=pm, rm=rm, combo_model=combo_model)
        p = SettingsProfilePresenter(view=view, model=m)
        # Не должен пробросить исключение
        p.on_apply_clicked()

    def test_generic_error_shows_error_and_returns_false(
        self,
        rm: FakeRM,
        combo_model: RecipeSlotComboModel,
        ui: SettingsProfileTabConfig,
        view: FakeView,
    ) -> None:
        pm = FakeProfileManager(profiles={"fast": {}}, raise_on_switch=ValueError("bad"))
        m = SettingsProfileModel(ui=ui, profile_manager=pm, rm=rm, combo_model=combo_model)
        p = SettingsProfilePresenter(view=view, model=m)
        result = p.on_apply_clicked()
        assert result is False
        assert len(view.errors) == 1

    def test_no_refresh_on_error(
        self,
        rm: FakeRM,
        combo_model: RecipeSlotComboModel,
        ui: SettingsProfileTabConfig,
        view: FakeView,
    ) -> None:
        err = ShmBudgetError(
            camera_count=8, ring_buffer_size=3, required_mb=600.0, budget_mb=64
        )
        pm = FakeProfileManager(profiles={"fast": {}}, raise_on_switch=err)
        m = SettingsProfileModel(ui=ui, profile_manager=pm, rm=rm, combo_model=combo_model)
        p = SettingsProfilePresenter(view=view, model=m)
        p.on_apply_clicked()
        assert view.refresh_calls == 0


# ---------------------------------------------------------------------------
# TestOnSaveClicked
# ---------------------------------------------------------------------------


class TestOnSaveClicked:
    def test_saves_settings_only_not_full_dump(
        self,
        presenter: SettingsProfilePresenter,
        profile_manager: FakeProfileManager,
        rm: FakeRM,
        view: FakeView,
    ) -> None:
        """save_profile_snapshot вызван со снимком только settings-регистра."""
        presenter.on_save_clicked()
        assert len(profile_manager.save_calls) == 1
        saved_id, saved_snapshot = profile_manager.save_calls[0]
        assert saved_id == view.current_profile_id()
        # Снимок — только содержимое settings, не весь model_dump_all
        expected_snapshot = rm.model_dump_all().get("settings", {})
        assert saved_snapshot == expected_snapshot

    def test_save_does_not_include_other_registers(
        self,
        presenter: SettingsProfilePresenter,
        profile_manager: FakeProfileManager,
        rm: FakeRM,
    ) -> None:
        """Убеждаемся, что снимок не содержит верхнего ключа 'settings'."""
        presenter.on_save_clicked()
        _, saved_snapshot = profile_manager.save_calls[0]
        # snapshot — это dict с полями вида camera_count, не {"settings": {...}}
        assert "settings" not in saved_snapshot

    def test_noop_when_rm_none(
        self,
        profile_manager: FakeProfileManager,
        combo_model: RecipeSlotComboModel,
        ui: SettingsProfileTabConfig,
        view: FakeView,
    ) -> None:
        m = SettingsProfileModel(
            ui=ui, profile_manager=profile_manager, rm=None, combo_model=combo_model
        )
        p = SettingsProfilePresenter(view=view, model=m)
        p.on_save_clicked()
        assert profile_manager.save_calls == []


# ---------------------------------------------------------------------------
# TestOnDefaultClicked
# ---------------------------------------------------------------------------


class TestOnDefaultClicked:
    def test_switches_to_default(
        self,
        presenter: SettingsProfilePresenter,
        profile_manager: FakeProfileManager,
    ) -> None:
        presenter.on_default_clicked()
        assert "default" in profile_manager.switch_calls

    def test_refresh_called_on_success(
        self,
        presenter: SettingsProfilePresenter,
        view: FakeView,
    ) -> None:
        presenter.on_default_clicked()
        assert view.refresh_calls == 1

    def test_returns_true_on_success(
        self,
        presenter: SettingsProfilePresenter,
    ) -> None:
        result = presenter.on_default_clicked()
        assert result is True

    def test_shm_budget_error_shows_error_returns_false(
        self,
        rm: FakeRM,
        combo_model: RecipeSlotComboModel,
        ui: SettingsProfileTabConfig,
        view: FakeView,
    ) -> None:
        err = ShmBudgetError(
            camera_count=8, ring_buffer_size=3, required_mb=600.0, budget_mb=64
        )
        pm = FakeProfileManager(profiles={"default": {}}, raise_on_switch=err)
        m = SettingsProfileModel(ui=ui, profile_manager=pm, rm=rm, combo_model=combo_model)
        p = SettingsProfilePresenter(view=view, model=m)
        result = p.on_default_clicked()
        assert result is False
        assert len(view.errors) == 1

    def test_no_refresh_on_error(
        self,
        rm: FakeRM,
        combo_model: RecipeSlotComboModel,
        ui: SettingsProfileTabConfig,
        view: FakeView,
    ) -> None:
        err = ShmBudgetError(
            camera_count=8, ring_buffer_size=3, required_mb=600.0, budget_mb=64
        )
        pm = FakeProfileManager(profiles={"default": {}}, raise_on_switch=err)
        m = SettingsProfileModel(ui=ui, profile_manager=pm, rm=rm, combo_model=combo_model)
        p = SettingsProfilePresenter(view=view, model=m)
        p.on_default_clicked()
        assert view.refresh_calls == 0


# ---------------------------------------------------------------------------
# TestOnLeafValueChanged
# ---------------------------------------------------------------------------


class TestOnLeafValueChanged:
    def test_valid_int_change_calls_set_field_value_with_int(
        self,
        presenter: SettingsProfilePresenter,
        rm: FakeRM,
    ) -> None:
        presenter.on_leaf_value_changed("settings", "settings.camera_count", "value", "4")
        assert rm._set_calls
        reg_name, field_name, value = rm._set_calls[-1]
        assert reg_name == "settings"
        assert field_name == "camera_count"
        assert value == 4
        assert isinstance(value, int)

    def test_invalid_value_rolls_back_to_previous(
        self,
        presenter: SettingsProfilePresenter,
        rm: FakeRM,
        view: FakeView,
    ) -> None:
        """Невалидное значение 'abc' для int-поля — rollback к предыдущему (1)."""
        # camera_count начальное = 1 (из FakeRM defaults)
        presenter.on_leaf_value_changed("settings", "settings.camera_count", "value", "abc")
        # coerce_string_to_value("abc", 1) → 1 (возврат предыдущего для int)
        # set_field_value должен быть вызван с 1
        assert rm._set_calls
        _, _, value = rm._set_calls[-1]
        assert value == 1

    def test_non_value_column_is_ignored(
        self,
        presenter: SettingsProfilePresenter,
        rm: FakeRM,
    ) -> None:
        presenter.on_leaf_value_changed("settings", "settings.camera_count", "info", "changed")
        assert rm._set_calls == []

    def test_non_value_column_param_is_ignored(
        self,
        presenter: SettingsProfilePresenter,
        rm: FakeRM,
    ) -> None:
        presenter.on_leaf_value_changed("settings", "settings.camera_count", "param", "changed")
        assert rm._set_calls == []

    def test_unknown_field_id_no_dots_is_ignored(
        self,
        presenter: SettingsProfilePresenter,
        rm: FakeRM,
    ) -> None:
        presenter.on_leaf_value_changed("settings", "no_dot_field", "value", "42")
        assert rm._set_calls == []

    def test_unknown_register_is_ignored(
        self,
        presenter: SettingsProfilePresenter,
        rm: FakeRM,
    ) -> None:
        """Регистр 'unknown' не существует в FakeRM — get_register вернёт None."""
        presenter.on_leaf_value_changed("unknown", "unknown.field", "value", "42")
        assert rm._set_calls == []

    def test_set_field_value_failure_rolls_back_cell_text(
        self,
        rm: FakeRM,
        combo_model: RecipeSlotComboModel,
        ui: SettingsProfileTabConfig,
        view: FakeView,
        profile_manager: FakeProfileManager,
    ) -> None:
        """При неудаче set_field_value — view.set_leaf_value_text вызван с предыдущим значением."""

        class _FailRM(FakeRM):
            def set_field_value(self, register_name, field_name, value):
                self._set_calls.append((register_name, field_name, value))
                return (False, "forced failure")

        fail_rm = _FailRM()
        m = SettingsProfileModel(
            ui=ui, profile_manager=profile_manager, rm=fail_rm, combo_model=combo_model
        )
        p = SettingsProfilePresenter(view=view, model=m)
        p.on_leaf_value_changed("settings", "settings.camera_count", "value", "999")
        # Presenter должен вызвать set_leaf_value_text с предыдущим значением (1)
        assert ("settings", "settings.camera_count") in view.leaf_texts
        assert view.leaf_texts[("settings", "settings.camera_count")] == "1"

    def test_noop_when_rm_none(
        self,
        profile_manager: FakeProfileManager,
        combo_model: RecipeSlotComboModel,
        ui: SettingsProfileTabConfig,
        view: FakeView,
    ) -> None:
        m = SettingsProfileModel(
            ui=ui, profile_manager=profile_manager, rm=None, combo_model=combo_model
        )
        p = SettingsProfilePresenter(view=view, model=m)
        # Не должен падать при rm=None
        p.on_leaf_value_changed("settings", "settings.camera_count", "value", "4")
        assert view.leaf_texts == {}
