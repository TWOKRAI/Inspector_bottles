"""test_recipes_presenter.py — Unit-тесты RecipesPresenter (MVP).

12 тестов:
- test_load_calls_refresh_list
- test_load_resets_buttons
- test_on_select_shows_recipe
- test_on_select_none_clears
- test_on_select_active_disables_button
- test_on_duplicate_success
- test_on_duplicate_failure
- test_on_create_via_store
- test_on_delete_with_confirm
- test_on_delete_no_confirm
- test_on_set_active_calls_replace
- test_on_set_active_no_replace_fn
- test_on_set_active_replace_error

Presenter тестируется без Qt-зависимостей.
IRecipesView мокируется через MagicMock(spec=IRecipesView).
RecipeStore реализован через FakeRecipeStore с raw-хранилищем.

Task F.4: перешёл с _FakeRecipeManager на FakeRecipeStore (RecipeStore Protocol).

Refs: plans/prototype-skeleton-2026-05/phase-5-recipes-manager-v2.md Task 5.6
      plans/2026-05-27_cross-tab-architecture/phase-f-legacy-removal.md Task F.4
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from multiprocess_prototype.domain.commands import ActivateRecipe
from multiprocess_prototype.domain.errors import DomainError
from multiprocess_prototype.domain.tests._fakes import FakeCommandDispatcher, FakeRecipeStore
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


def _make_recipe_raw(slug: str = "cup") -> dict:
    """Минимальный v2-рецепт raw dict."""
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


def _make_store(
    slugs: list[str] | None = None,
    active: str | None = None,
) -> FakeRecipeStore:
    """Создать FakeRecipeStore с raw-рецептами."""
    raw: dict[str, dict] = {}
    if slugs:
        for slug in slugs:
            raw[slug] = _make_recipe_raw(slug)
    return FakeRecipeStore(raw=raw, active=active)


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_view() -> MagicMock:
    return _make_view()


@pytest.fixture()
def store() -> FakeRecipeStore:
    return _make_store()


@pytest.fixture()
def presenter(store: FakeRecipeStore, mock_view: MagicMock) -> RecipesPresenter:
    return RecipesPresenter(store=store, view=mock_view)


# ---------------------------------------------------------------------------
# Тест 1: load() -> view.refresh_list вызван со списком из store.list()
# ---------------------------------------------------------------------------


def test_load_calls_refresh_list(
    mock_view: MagicMock,
) -> None:
    """load() -> view.refresh_list вызван с актуальным списком slug'ов."""
    store = _make_store(slugs=["bottle", "cup"])
    presenter = RecipesPresenter(store=store, view=mock_view)

    presenter.load()

    # FakeRecipeStore.list() возвращает sorted tuple
    mock_view.refresh_list.assert_called_once_with(["bottle", "cup"])


# ---------------------------------------------------------------------------
# Тест 2: load() -> view.set_buttons_state(False, False) вызван
# ---------------------------------------------------------------------------


def test_load_resets_buttons(
    presenter: RecipesPresenter,
    mock_view: MagicMock,
) -> None:
    """load() -> view.set_buttons_state(False, False) вызван (сброс выбора)."""
    presenter.load()

    mock_view.set_buttons_state.assert_called_once_with(False, False)


# ---------------------------------------------------------------------------
# Тест 3: on_select('cup') -> view.show_recipe вызван с данными рецепта
# ---------------------------------------------------------------------------


def test_on_select_shows_recipe(
    mock_view: MagicMock,
) -> None:
    """on_select('cup') -> view.show_recipe('cup', data) вызван."""
    store = _make_store(slugs=["cup"])
    presenter = RecipesPresenter(store=store, view=mock_view)

    presenter.on_select("cup")

    # show_recipe должен быть вызван с непустым data (dict)
    mock_view.show_recipe.assert_called_once()
    call_args = mock_view.show_recipe.call_args
    assert call_args[0][0] == "cup"  # slug
    assert isinstance(call_args[0][1], dict)  # data — dict из raw store


# ---------------------------------------------------------------------------
# Тест 4: on_select(None) -> show_recipe(None, None) и set_buttons_state(False, False)
# ---------------------------------------------------------------------------


def test_on_select_none_clears(
    presenter: RecipesPresenter,
    mock_view: MagicMock,
) -> None:
    """on_select(None) -> view.show_recipe(None, None) и set_buttons_state(False, False)."""
    presenter.on_select(None)

    mock_view.show_recipe.assert_called_once_with(None, None)
    mock_view.set_buttons_state.assert_called_once_with(False, False)


# ---------------------------------------------------------------------------
# Тест 5: on_select с активным slug -> set_buttons_state(True, True)
# ---------------------------------------------------------------------------


def test_on_select_active_disables_button(
    mock_view: MagicMock,
) -> None:
    """Выбрать slug == активный -> set_buttons_state(True, True)."""
    store = _make_store(slugs=["cup"], active="cup")
    presenter = RecipesPresenter(store=store, view=mock_view)

    presenter.on_select("cup")

    # Последний вызов set_buttons_state должен быть (True, True)
    mock_view.set_buttons_state.assert_called_with(True, True)


# ---------------------------------------------------------------------------
# Тест 6: on_duplicate успешный -> load() вызван (через refresh_list)
# ---------------------------------------------------------------------------


def test_on_duplicate_success(
    mock_view: MagicMock,
) -> None:
    """duplicate возвращает True -> load() вызывается (refresh_list вызван)."""
    store = _make_store(slugs=["cup"])
    presenter = RecipesPresenter(store=store, view=mock_view)

    presenter._selected_slug = "cup"
    presenter.on_duplicate()

    # После on_duplicate -> load() -> refresh_list должен быть вызван
    mock_view.refresh_list.assert_called()
    # И в store должна появиться копия
    assert "cup_copy" in store._raw


# ---------------------------------------------------------------------------
# Тест 7: on_duplicate() при ошибке -> view.show_error вызван
# ---------------------------------------------------------------------------


def test_on_duplicate_failure(
    mock_view: MagicMock,
) -> None:
    """duplicate не удаётся (slug не существует) -> view.show_error вызван."""
    store = _make_store()  # пустой
    presenter = RecipesPresenter(store=store, view=mock_view)

    presenter._selected_slug = "nonexistent"
    presenter.on_duplicate()

    mock_view.show_error.assert_called_once()


# ---------------------------------------------------------------------------
# Тест 7b: on_create через store.save_raw (без файловой системы)
# ---------------------------------------------------------------------------


def test_on_create_via_store(
    mock_view: MagicMock,
) -> None:
    """on_create записывает через store.save_raw, не трогая файловую систему."""
    store = _make_store()
    presenter = RecipesPresenter(store=store, view=mock_view)

    presenter.on_create("Test Recipe", "описание")

    # slug = test_recipe
    assert "test_recipe" in store._raw
    raw = store._raw["test_recipe"]
    assert raw["version"] == 2
    assert raw["name"] == "Test Recipe"
    assert raw["description"] == "описание"
    mock_view.refresh_list.assert_called()


# ---------------------------------------------------------------------------
# Тест 8: on_delete с confirm=True -> store.delete вызван
# ---------------------------------------------------------------------------


def test_on_delete_with_confirm(
    mock_view: MagicMock,
) -> None:
    """confirm_delete -> True -> рецепт удалён из store."""
    mock_view.confirm_delete.return_value = True
    store = _make_store(slugs=["cup"])
    presenter = RecipesPresenter(store=store, view=mock_view)

    presenter._selected_slug = "cup"
    presenter.on_delete()

    # Рецепт удалён из raw-хранилища
    assert "cup" not in store._raw


# ---------------------------------------------------------------------------
# Тест 9: on_delete с confirm=False -> рецепт НЕ удалён
# ---------------------------------------------------------------------------


def test_on_delete_no_confirm(
    mock_view: MagicMock,
) -> None:
    """confirm_delete -> False -> рецепт остаётся в store."""
    mock_view.confirm_delete.return_value = False
    store = _make_store(slugs=["cup"])
    presenter = RecipesPresenter(store=store, view=mock_view)

    presenter._selected_slug = "cup"
    presenter.on_delete()

    # Рецепт на месте
    assert "cup" in store._raw


# ---------------------------------------------------------------------------
# Тест 10: on_set_active -> apply_topology_fn вызывается с blueprint dict
# ---------------------------------------------------------------------------


def test_on_set_active_calls_replace(
    mock_view: MagicMock,
) -> None:
    """on_set_active вызывает apply_topology_fn с blueprint dict."""
    blueprint_data = {
        "processes": [{"process_name": "worker_1", "class": "Worker", "plugins": []}],
        "wires": [],
    }
    raw = {
        "version": 2,
        "name": "cup",
        "description": "test",
        "blueprint": blueprint_data,
        "active_services": [],
        "display_bindings": [],
    }
    store = FakeRecipeStore(raw={"cup": raw})

    replace_fn = MagicMock(return_value={"success": True, "replaced": ["worker_1"]})
    presenter = RecipesPresenter(
        store=store,
        view=mock_view,
        apply_topology_fn=replace_fn,
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
# Тест 11: on_set_active без replace_fn -> set_active работает без ошибки
# ---------------------------------------------------------------------------


def test_on_set_active_no_replace_fn(
    mock_view: MagicMock,
) -> None:
    """_apply_topology_fn = None -> on_set_active работает без ошибки."""
    store = _make_store(slugs=["cup"])
    presenter = RecipesPresenter(
        store=store,
        view=mock_view,
        apply_topology_fn=None,
    )

    presenter._selected_slug = "cup"
    # Не должно бросать исключений
    presenter.on_set_active()

    # show_error не должен вызываться
    mock_view.show_error.assert_not_called()
    # refresh_list должен быть вызван (через load())
    mock_view.refresh_list.assert_called()


# ---------------------------------------------------------------------------
# Тест 12: on_set_active с replace_fn -> ошибка -> view.show_error вызван
# ---------------------------------------------------------------------------


def test_on_set_active_replace_error(
    mock_view: MagicMock,
) -> None:
    """apply_topology_fn возвращает success=False -> view.show_error вызван."""
    store = _make_store(slugs=["cup"])
    replace_fn = MagicMock(return_value={"success": False, "error": "Процесс не стартовал"})
    presenter = RecipesPresenter(
        store=store,
        view=mock_view,
        apply_topology_fn=replace_fn,
    )

    presenter._selected_slug = "cup"
    presenter.on_set_active()

    mock_view.show_error.assert_called_once()
    error_msg = mock_view.show_error.call_args[0][0]
    assert "Процесс не стартовал" in error_msg


# ---------------------------------------------------------------------------
# Тест 13: on_save -> текущая топология (topology_store) сохраняется в рецепт
# ---------------------------------------------------------------------------


def test_on_save_persists_topology(mock_view: MagicMock) -> None:
    """on_save пишет живую топологию в top-level blueprint рецепта (displays внутри).

    Fix recipe-v3-engine-decouple: раньше писалось в legacy-вложение data.blueprint
    (его reader не понимал → порча). Теперь — top-level blueprint, displays внутри
    blueprint.displays (round-trip с editor/backend-launch).
    """
    store = _make_store(slugs=["cup"])

    class _FakeTopologyStore:
        def load(self) -> dict:
            return {
                "processes": [{"process_name": "p1", "plugins": []}],
                "wires": [{"source": "p1.a.out", "target": "p2.b.in"}],
                "displays": [{"node_id": "p1.a.out", "display_id": "main"}],
            }

    presenter = RecipesPresenter(
        store=store,
        view=mock_view,
        topology_store=_FakeTopologyStore(),
    )
    presenter._selected_slug = "cup"

    ok = presenter.on_save()

    assert ok is True
    mock_view.show_error.assert_not_called()
    saved = store.read_raw("cup")
    assert "data" not in saved  # legacy-вложение убрано
    assert saved["blueprint"]["processes"][0]["process_name"] == "p1"
    assert saved["blueprint"]["wires"][0]["source"] == "p1.a.out"
    assert saved["blueprint"]["displays"][0]["display_id"] == "main"


def test_on_save_no_topology_store(mock_view: MagicMock) -> None:
    """on_save без topology_store -> show_error, False (graceful)."""
    store = _make_store(slugs=["cup"])
    presenter = RecipesPresenter(store=store, view=mock_view, topology_store=None)
    presenter._selected_slug = "cup"

    assert presenter.on_save() is False
    mock_view.show_error.assert_called_once()


# ---------------------------------------------------------------------------
# G.6.5: on_set_active → dispatch(ActivateRecipe) когда commands задан
# ---------------------------------------------------------------------------


class _RecordingDispatcher(FakeCommandDispatcher):
    """FakeCommandDispatcher, запоминающий kwargs последнего dispatch."""

    def __init__(self) -> None:
        super().__init__()
        self.dispatch_kwargs: dict = {}

    def dispatch(self, command, *, coalesce_key=None, undoable=True):  # type: ignore[override]
        self.dispatch_kwargs = {"coalesce_key": coalesce_key, "undoable": undoable}
        return super().dispatch(command)


class _RaisingDispatcher(FakeCommandDispatcher):
    """Dispatcher, бросающий DomainError на dispatch (невалидный blueprint)."""

    def dispatch(self, command, *, coalesce_key=None, undoable=True):  # type: ignore[override]
        raise DomainError("recipe blueprint invalid")


def test_on_set_active_dispatches_activate_recipe(mock_view: MagicMock) -> None:
    """commands задан → on_set_active dispatch'ит ActivateRecipe(slug)."""
    store = _make_store(slugs=["cup"])
    commands = _RecordingDispatcher()
    presenter = RecipesPresenter(store=store, view=mock_view, commands=commands)

    presenter.on_set_active("cup")

    assert isinstance(commands.last_command, ActivateRecipe)
    assert commands.last_command.slug == "cup"
    # undoable=False — переключение рецепта не попадает в Ctrl+Z историю
    assert commands.dispatch_kwargs["undoable"] is False
    # persist флага активного рецепта выполнен
    assert store.get_active() == "cup"


def test_on_set_active_domain_error_graceful(mock_view: MagicMock) -> None:
    """DomainError из dispatch → show_error, set_active НЕ выполнен."""
    store = _make_store(slugs=["cup"])
    presenter = RecipesPresenter(store=store, view=mock_view, commands=_RaisingDispatcher())

    presenter.on_set_active("cup")

    mock_view.show_error.assert_called_once()
    assert store.get_active() is None  # persist не произошёл (return до set_active)


def test_on_set_active_no_commands_skips_dispatch(mock_view: MagicMock) -> None:
    """commands=None → legacy-путь: dispatch не зовётся, set_active выполнен."""
    store = _make_store(slugs=["cup"])
    presenter = RecipesPresenter(store=store, view=mock_view)  # commands=None

    presenter.on_set_active("cup")

    assert store.get_active() == "cup"
    mock_view.show_error.assert_not_called()
