# multiprocess_prototype_v3/tests/unit/test_recipes_register_presenter.py
"""Unit-тесты `RegisterRecipePresenter` — логика без Qt (Phase 1, Task 1.5).

Presenter импортируется через цепочку `.model` → `frontend_module.interfaces` →
`frontend_module/__init__.py` → Qt. Поэтому тест требует установленного PyQt5
(в venv без PyQt5 — skip через importorskip, как в test_frontend_config_settings_path.py).
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("PyQt5", reason="presenter импортирует frontend_module.interfaces (тянет PyQt5)")

from multiprocess_prototype_v3.frontend.managers.access_context import AccessContext  # noqa: E402
from multiprocess_prototype_v3.frontend.widgets.recipes_widget.model import (
    RegisterRecipeModel,  # noqa: E402
)
from multiprocess_prototype_v3.frontend.widgets.recipes_widget.presenter import (
    RegisterRecipePresenter,  # noqa: E402
)
from multiprocess_prototype_v3.frontend.widgets.settings_recipe_widget.schemas import (
    RecipesTabConfig,  # noqa: E402
)


class FakeView:
    def __init__(self, slot: int = 1) -> None:
        self.slot_value = slot
        self.refreshed = 0
        self.leaf_texts: list[tuple[str, str, str]] = []

    def parse_slot(self) -> int:
        return self.slot_value

    def refresh_table_rows(self) -> None:
        self.refreshed += 1

    def set_leaf_value_text(self, group_id: str, field_id: str, text: str) -> None:
        self.leaf_texts.append((group_id, field_id, text))


class FakeRegister:
    """Простая Pydantic-подобная схема с одним int полем."""

    def __init__(self, initial: int = 0) -> None:
        self._val = initial

    def model_dump(self) -> dict[str, Any]:
        return {"field_a": self._val}

    @property
    def field_a(self) -> int:
        return self._val

    @field_a.setter
    def field_a(self, value: int) -> None:
        self._val = value


class FakeRM:
    """Мок IRegistersManagerGui — минимум методов, которые использует presenter."""

    def __init__(self) -> None:
        self.reg = FakeRegister(initial=7)
        self.set_calls: list[tuple[str, str, Any]] = []
        self.fail_next = False

    def get_register(self, name: str):
        return self.reg if name == "my_register" else None

    def register_names(self) -> list[str]:
        return ["my_register"]

    def set_field_value(self, register_name: str, field_name: str, value: Any):
        self.set_calls.append((register_name, field_name, value))
        if self.fail_next:
            self.fail_next = False
            return False, "forced failure"
        if register_name == "my_register" and hasattr(self.reg, field_name):
            setattr(self.reg, field_name, value)
        return True, None

    def get_field_metadata(self, register_name: str, field_name: str):
        return {}

    def model_dump_all(self) -> dict[str, Any]:
        return {"my_register": self.reg.model_dump()}


class FakeRecipeManager:
    def __init__(self) -> None:
        self.current_slot = 0
        self.load_calls: list[tuple[Any, str]] = []
        self.save_calls: list[tuple[Any, str]] = []
        self.load_result = True

    def set_current_register_recipe_number(self, idx: int) -> None:
        self.current_slot = idx

    def get_current_register_recipe_number(self) -> int:
        return self.current_slot

    def load_recipe_to_registers(self, rm: Any, slot_id: str) -> bool:
        self.load_calls.append((rm, slot_id))
        return self.load_result

    def save_registers_to_recipe(self, rm: Any, slot_id: str) -> bool:
        self.save_calls.append((rm, slot_id))
        return True

    def list_slots(self) -> list[str]:
        return ["0", "1", "2"]


@pytest.fixture()
def ui() -> RecipesTabConfig:
    return RecipesTabConfig()


@pytest.fixture()
def rm() -> FakeRM:
    return FakeRM()


@pytest.fixture()
def mgr() -> FakeRecipeManager:
    return FakeRecipeManager()


@pytest.fixture()
def view() -> FakeView:
    return FakeView(slot=1)


@pytest.fixture()
def access_ctx() -> AccessContext:
    return AccessContext.default()


@pytest.fixture()
def presenter(
    view: FakeView,
    rm: FakeRM,
    mgr: FakeRecipeManager,
    access_ctx: AccessContext,
    ui: RecipesTabConfig,
) -> RegisterRecipePresenter:
    model = RegisterRecipeModel(rm=rm, recipe_manager=mgr, access_ctx=access_ctx, ui=ui)
    return RegisterRecipePresenter(view=view, model=model)


class TestOnLoadClicked:
    def test_parses_slot_and_loads_recipe(
        self, presenter: RegisterRecipePresenter, view: FakeView, mgr: FakeRecipeManager, rm: FakeRM
    ) -> None:
        view.slot_value = 2
        presenter.on_load_clicked()
        assert mgr.current_slot == 2
        assert mgr.load_calls == [(rm, "2")]
        assert view.refreshed == 1

    def test_noop_when_manager_none(
        self, view: FakeView, rm: FakeRM, access_ctx: AccessContext, ui: RecipesTabConfig
    ) -> None:
        model = RegisterRecipeModel(rm=rm, recipe_manager=None, access_ctx=access_ctx, ui=ui)
        p = RegisterRecipePresenter(view=view, model=model)
        p.on_load_clicked()
        assert view.refreshed == 0


class TestOnSaveClicked:
    def test_parses_slot_and_saves_recipe(
        self, presenter: RegisterRecipePresenter, view: FakeView, mgr: FakeRecipeManager, rm: FakeRM
    ) -> None:
        view.slot_value = 3
        presenter.on_save_clicked()
        assert mgr.current_slot == 3
        assert mgr.save_calls == [(rm, "3")]


class TestOnDefaultClicked:
    def test_loads_default_slot_then_default_value_legacy(
        self, presenter: RegisterRecipePresenter, mgr: FakeRecipeManager, view: FakeView
    ) -> None:
        mgr.load_result = True
        presenter.on_default_clicked()
        # DEFAULT_RECIPE_SLOT_ID = "default" в v3.
        assert mgr.load_calls[0][1] == "default"
        assert view.refreshed == 1

    def test_falls_back_to_default_value_when_default_missing(
        self, presenter: RegisterRecipePresenter, mgr: FakeRecipeManager
    ) -> None:
        mgr.load_result = False
        presenter.on_default_clicked()
        # При неудаче первого load — fallback на legacy "default_value".
        assert [call[1] for call in mgr.load_calls] == ["default", "default_value"]


class TestOnLeafValueChanged:
    def test_int_field_is_coerced_from_string(
        self, presenter: RegisterRecipePresenter, rm: FakeRM, view: FakeView
    ) -> None:
        # Единственный регистр FakeRM — "my_register" с полем "field_a".
        # field_id == f"{register_name}.{field_name}" в build_recipe_rows.
        field_id = "my_register.field_a"
        presenter.on_leaf_value_changed("my_register", field_id, "value", "42")
        # set_field_value вызван с int 42, не "42".
        assert rm.set_calls
        register_name, field_name, value = rm.set_calls[-1]
        assert register_name == "my_register"
        assert field_name == "field_a"
        assert value == 42
        assert isinstance(value, int)

    def test_non_value_column_is_ignored(
        self, presenter: RegisterRecipePresenter, rm: FakeRM
    ) -> None:
        presenter.on_leaf_value_changed("my_register", "my_register.field_a", "info", "changed")
        assert rm.set_calls == []

    def test_unknown_field_id_is_ignored(
        self, presenter: RegisterRecipePresenter, rm: FakeRM
    ) -> None:
        presenter.on_leaf_value_changed("my_register", "unknown.field", "value", "100")
        assert rm.set_calls == []

    def test_set_field_value_failure_rolls_back_cell_text(
        self, presenter: RegisterRecipePresenter, rm: FakeRM, view: FakeView
    ) -> None:
        rm.fail_next = True
        field_id = "my_register.field_a"
        presenter.on_leaf_value_changed("my_register", field_id, "value", "42")
        # Presenter должен позвать set_leaf_value_text с предыдущим значением (7).
        assert any("7" in text for _, _, text in view.leaf_texts)


class TestInitialSlot:
    def test_returns_from_model_compute_initial_slot(
        self, presenter: RegisterRecipePresenter, mgr: FakeRecipeManager
    ) -> None:
        mgr.set_current_register_recipe_number(5)
        assert presenter.initial_slot() == 5


class TestCurrentFieldValue:
    def test_returns_value_from_register_model_dump(
        self, presenter: RegisterRecipePresenter
    ) -> None:
        assert presenter.current_field_value("my_register", "field_a") == 7

    def test_returns_none_for_missing_register(
        self, presenter: RegisterRecipePresenter
    ) -> None:
        assert presenter.current_field_value("missing", "field_a") is None
