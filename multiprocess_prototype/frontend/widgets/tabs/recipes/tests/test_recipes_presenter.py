"""test_recipes_presenter.py — Unit-тесты RecipesPresenter (MVP).

12 тестов:
- test_load_calls_refresh_list
- test_load_resets_buttons
- test_on_select_shows_recipe
- test_on_select_none_clears
- test_on_select_active_disables_button
- test_on_duplicate_success
- test_on_duplicate_failure
- test_on_delete_with_confirm
- test_on_delete_no_confirm
- test_on_set_active_calls_replace
- test_on_set_active_no_replace_fn
- test_on_set_active_replace_error

Presenter тестируется без Qt-зависимостей.
IRecipesView мокируется через MagicMock(spec=IRecipesView).
RecipeManager мокируется через MagicMock или FakeRecipeManager с tmp_path.

Refs: plans/prototype-skeleton-2026-05/phase-5-recipes-manager-v2.md Task 5.6
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from multiprocess_prototype.frontend.widgets.tabs.recipes.presenter import (
    RecipesPresenter,
)
from multiprocess_prototype.frontend.widgets.tabs.recipes.view import IRecipesView


# ---------------------------------------------------------------------------
# Вспомогательные фабрики
# ---------------------------------------------------------------------------


def _make_view() -> MagicMock:
    """Создать mock, совместимый с IRecipesView."""
    view = MagicMock(spec=IRecipesView)
    # confirm_delete возвращает True по умолчанию
    view.confirm_delete.return_value = True
    return view


def _make_recipe_data(slug: str = "cup", active_slug: str | None = None) -> dict:
    """Минимальный v2-рецепт dict."""
    return {
        "version": 2,
        "name": slug,
        "description": "Тестовый рецепт",
        "blueprint": {
            "processes": [{"process_name": "worker_1", "class": "Worker", "plugins": []}],
            "wires": [],
        },
        "active_services": [],
        "display_bindings": [],
    }


def _write_recipe(recipes_dir: Path, slug: str, data: dict | None = None) -> None:
    """Записать YAML рецепта в директорию."""
    recipe_data = data or _make_recipe_data(slug)
    path = recipes_dir / f"{slug}.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(recipe_data, f, default_flow_style=False, allow_unicode=True)


class _FakeEngine:
    """Минимальный fake для RecipeEngine API, нужного presenter'у."""

    def __init__(self, recipes_dir: Path) -> None:
        self.recipes_dir = recipes_dir

    def get_active(self) -> str | None:
        return None


class _FakeRecipeManager:
    """Fake RecipeManager с реальным recipes_dir для тестов, требующих YAML.

    Поддерживает настраиваемые возвращаемые значения через атрибуты.
    """

    def __init__(self, recipes_dir: Path, active: str | None = None) -> None:
        self._active = active
        self._engine = _FakeEngine(recipes_dir)
        self._list: list[str] = []
        self._duplicate_result: bool = True
        self._set_active_result: bool = True

    def list(self) -> list[str]:
        return list(self._list)

    def get_active(self) -> str | None:
        return self._active

    def set_active(self, slug: str) -> bool:
        if self._set_active_result:
            self._active = slug
        return self._set_active_result

    def duplicate(self, source_slug: str, new_slug: str) -> bool:
        return self._duplicate_result

    def delete(self, slug: str) -> bool:
        if slug in self._list:
            self._list.remove(slug)
        return True


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture()
def recipes_dir(tmp_path: Path) -> Path:
    """Временная директория для рецептов."""
    d = tmp_path / "recipes"
    d.mkdir()
    return d


@pytest.fixture()
def mock_view() -> MagicMock:
    return _make_view()


@pytest.fixture()
def fake_manager(recipes_dir: Path) -> _FakeRecipeManager:
    return _FakeRecipeManager(recipes_dir=recipes_dir)


@pytest.fixture()
def presenter(fake_manager: _FakeRecipeManager, mock_view: MagicMock) -> RecipesPresenter:
    return RecipesPresenter(recipe_manager=fake_manager, view=mock_view)


# ---------------------------------------------------------------------------
# Тест 1: load() → view.refresh_list вызван со списком из recipe_manager.list()
# ---------------------------------------------------------------------------


def test_load_calls_refresh_list(
    presenter: RecipesPresenter,
    fake_manager: _FakeRecipeManager,
    mock_view: MagicMock,
) -> None:
    """load() → view.refresh_list вызван с актуальным списком slug'ов."""
    fake_manager._list = ["cup", "bottle"]

    presenter.load()

    mock_view.refresh_list.assert_called_once_with(["cup", "bottle"])


# ---------------------------------------------------------------------------
# Тест 2: load() → view.set_buttons_state(False, False) вызван
# ---------------------------------------------------------------------------


def test_load_resets_buttons(
    presenter: RecipesPresenter,
    mock_view: MagicMock,
) -> None:
    """load() → view.set_buttons_state(False, False) вызван (сброс выбора)."""
    presenter.load()

    mock_view.set_buttons_state.assert_called_once_with(False, False)


# ---------------------------------------------------------------------------
# Тест 3: on_select('cup') → view.show_recipe вызван с данными рецепта
# ---------------------------------------------------------------------------


def test_on_select_shows_recipe(
    presenter: RecipesPresenter,
    fake_manager: _FakeRecipeManager,
    mock_view: MagicMock,
    recipes_dir: Path,
) -> None:
    """on_select('cup') → view.show_recipe('cup', data) вызван."""
    _write_recipe(recipes_dir, "cup")

    presenter.on_select("cup")

    # show_recipe должен быть вызван с непустым data (dict)
    mock_view.show_recipe.assert_called_once()
    call_args = mock_view.show_recipe.call_args
    assert call_args[0][0] == "cup"  # slug
    assert isinstance(call_args[0][1], dict)  # data — dict из YAML


# ---------------------------------------------------------------------------
# Тест 4: on_select(None) → show_recipe(None, None) и set_buttons_state(False, False)
# ---------------------------------------------------------------------------


def test_on_select_none_clears(
    presenter: RecipesPresenter,
    mock_view: MagicMock,
) -> None:
    """on_select(None) → view.show_recipe(None, None) и set_buttons_state(False, False)."""
    presenter.on_select(None)

    mock_view.show_recipe.assert_called_once_with(None, None)
    mock_view.set_buttons_state.assert_called_once_with(False, False)


# ---------------------------------------------------------------------------
# Тест 5: on_select с активным slug → set_buttons_state(True, True)
# ---------------------------------------------------------------------------


def test_on_select_active_disables_button(
    recipes_dir: Path,
    mock_view: MagicMock,
) -> None:
    """Выбрать slug == активный → set_buttons_state(True, True)."""
    _write_recipe(recipes_dir, "cup")
    manager = _FakeRecipeManager(recipes_dir=recipes_dir, active="cup")
    presenter = RecipesPresenter(recipe_manager=manager, view=mock_view)

    presenter.on_select("cup")

    # Последний вызов set_buttons_state должен быть (True, True)
    mock_view.set_buttons_state.assert_called_with(True, True)


# ---------------------------------------------------------------------------
# Тест 6: on_duplicate успешный → load() вызван (через refresh_list)
# ---------------------------------------------------------------------------


def test_on_duplicate_success(
    presenter: RecipesPresenter,
    fake_manager: _FakeRecipeManager,
    mock_view: MagicMock,
    recipes_dir: Path,
) -> None:
    """duplicate возвращает True → load() вызывается (refresh_list вызван)."""
    fake_manager._list = ["cup"]
    fake_manager._duplicate_result = True
    _write_recipe(recipes_dir, "cup")

    presenter._selected_slug = "cup"
    presenter.on_duplicate()

    # После on_duplicate → load() → refresh_list должен быть вызван
    mock_view.refresh_list.assert_called()


# ---------------------------------------------------------------------------
# Тест 7: on_duplicate() при ошибке → view.show_error вызван
# ---------------------------------------------------------------------------


def test_on_duplicate_failure(
    presenter: RecipesPresenter,
    fake_manager: _FakeRecipeManager,
    mock_view: MagicMock,
    recipes_dir: Path,
) -> None:
    """duplicate возвращает False → view.show_error вызван."""
    fake_manager._duplicate_result = False
    _write_recipe(recipes_dir, "cup")

    presenter._selected_slug = "cup"
    presenter.on_duplicate()

    mock_view.show_error.assert_called_once()


# ---------------------------------------------------------------------------
# Тест 8: on_delete с confirm=True → recipe_manager.delete вызван
# ---------------------------------------------------------------------------


def test_on_delete_with_confirm(
    presenter: RecipesPresenter,
    fake_manager: _FakeRecipeManager,
    mock_view: MagicMock,
) -> None:
    """confirm_delete → True → recipe_manager.delete('cup') вызван."""
    mock_view.confirm_delete.return_value = True
    fake_manager._list = ["cup"]

    presenter._selected_slug = "cup"
    presenter.on_delete()

    # Проверяем что delete был вызван с 'cup'
    # fake_manager.delete убирает из списка — список теперь пустой
    assert "cup" not in fake_manager.list()


# ---------------------------------------------------------------------------
# Тест 9: on_delete с confirm=False → recipe_manager.delete НЕ вызван
# ---------------------------------------------------------------------------


def test_on_delete_no_confirm(
    presenter: RecipesPresenter,
    fake_manager: _FakeRecipeManager,
    mock_view: MagicMock,
) -> None:
    """confirm_delete → False → recipe_manager.delete НЕ вызывается."""
    mock_view.confirm_delete.return_value = False
    fake_manager._list = ["cup"]

    presenter._selected_slug = "cup"
    presenter.on_delete()

    # Список не изменился — 'cup' на месте
    assert "cup" in fake_manager.list()


# ---------------------------------------------------------------------------
# Тест 10: on_set_active → replace_blueprint_fn вызывается с blueprint dict
# ---------------------------------------------------------------------------


def test_on_set_active_calls_replace(
    mock_view: MagicMock,
    recipes_dir: Path,
) -> None:
    """on_set_active вызывает replace_blueprint_fn с blueprint dict из YAML."""
    blueprint_data = {
        "processes": [{"process_name": "worker_1", "class": "Worker", "plugins": []}],
        "wires": [],
    }
    _write_recipe(
        recipes_dir,
        "cup",
        data={
            "version": 2,
            "name": "cup",
            "description": "test",
            "blueprint": blueprint_data,
            "active_services": [],
            "display_bindings": [],
        },
    )

    manager = _FakeRecipeManager(recipes_dir=recipes_dir)
    replace_fn = MagicMock(return_value={"success": True, "replaced": ["worker_1"]})
    presenter = RecipesPresenter(
        recipe_manager=manager,
        view=mock_view,
        replace_blueprint_fn=replace_fn,
    )

    presenter._selected_slug = "cup"
    presenter.on_set_active()

    # replace_fn должен быть вызван с dict blueprint (Dict at Boundary)
    replace_fn.assert_called_once()
    passed_blueprint = replace_fn.call_args[0][0]
    assert isinstance(passed_blueprint, dict)
    assert "processes" in passed_blueprint
    assert passed_blueprint["processes"][0]["process_name"] == "worker_1"


# ---------------------------------------------------------------------------
# Тест 11: on_set_active без replace_fn → set_active вызывается без ошибки
# ---------------------------------------------------------------------------


def test_on_set_active_no_replace_fn(
    mock_view: MagicMock,
    recipes_dir: Path,
) -> None:
    """_replace_blueprint_fn = None → on_set_active работает без ошибки (деградация)."""
    _write_recipe(recipes_dir, "cup")
    manager = _FakeRecipeManager(recipes_dir=recipes_dir)
    presenter = RecipesPresenter(
        recipe_manager=manager,
        view=mock_view,
        replace_blueprint_fn=None,  # явный None
    )

    presenter._selected_slug = "cup"
    # Не должно бросать исключений
    presenter.on_set_active()

    # show_error не должен вызываться
    mock_view.show_error.assert_not_called()
    # refresh_list должен быть вызван (через load())
    mock_view.refresh_list.assert_called()


# ---------------------------------------------------------------------------
# Тест 12: on_set_active с replace_fn → ошибка → view.show_error вызван
# ---------------------------------------------------------------------------


def test_on_set_active_replace_error(
    mock_view: MagicMock,
    recipes_dir: Path,
) -> None:
    """replace_blueprint_fn возвращает success=False → view.show_error вызван."""
    _write_recipe(recipes_dir, "cup")
    manager = _FakeRecipeManager(recipes_dir=recipes_dir)
    replace_fn = MagicMock(return_value={"success": False, "error": "Процесс не стартовал"})
    presenter = RecipesPresenter(
        recipe_manager=manager,
        view=mock_view,
        replace_blueprint_fn=replace_fn,
    )

    presenter._selected_slug = "cup"
    presenter.on_set_active()

    mock_view.show_error.assert_called_once()
    error_msg = mock_view.show_error.call_args[0][0]
    assert "Процесс не стартовал" in error_msg
