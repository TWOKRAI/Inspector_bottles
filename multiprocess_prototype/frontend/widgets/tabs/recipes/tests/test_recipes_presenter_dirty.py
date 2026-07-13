# -*- coding: utf-8 -*-
"""RS-4: dirty-контур при активации рецепта — подтверждение перед потерей правок.

C-2: активация другого рецепта МОЛЧА выбрасывала несохранённые правки графа. Теперь
при dirty-редакторе presenter спрашивает view.confirm_discard_changes() ДО любых
side-effects. Проверяем три исхода (cancel / discard / save) + характеризацию чистого
пути (без dirty диалога нет, поведение как до RS-4).

Refs: plans/2026-07-06_constructor-master/plan.md (RS-4),
      docs/audits/2026-07-12_recipe-lifecycle-audit.md (C-2)
"""

from __future__ import annotations

from unittest.mock import MagicMock

from multiprocess_prototype.domain.commands import ActivateRecipe
from multiprocess_prototype.domain.entities import Topology
from multiprocess_prototype.domain.tests._fakes import (
    FakeCommandDispatcher,
    FakeRecipeStore,
    FakeTopologyRepository,
)
from multiprocess_prototype.domain.topology_session import TopologySession
from multiprocess_prototype.frontend.widgets.tabs.recipes.presenter import RecipesPresenter
from multiprocess_prototype.frontend.widgets.tabs.recipes.view import IRecipesView


def _recipe_raw(slug: str) -> dict:
    return {
        "version": 2,
        "name": slug,
        "description": "test",
        "blueprint": {
            "processes": [{"process_name": "worker_1", "class": "Worker", "plugins": []}],
            "wires": [],
        },
        "active_services": [],
        "display_bindings": [],
    }


def _view(choice: str = "cancel") -> MagicMock:
    view = MagicMock(spec=IRecipesView)
    view.confirm_discard_changes.return_value = choice
    return view


def _dirty_session() -> TopologySession:
    s = TopologySession()
    s.mark_edited()  # dirty=True, diverged=True
    assert s.dirty is True
    return s


# ---------------------------------------------------------------------------
# cancel → активация НЕ происходит (нет dispatch, active не сменился)
# ---------------------------------------------------------------------------


def test_activate_dirty_cancel_aborts() -> None:
    """dirty + «Отмена» → ActivateRecipe не диспатчится, активный рецепт не сменён."""
    store = FakeRecipeStore(raw={"cup": _recipe_raw("cup"), "old": _recipe_raw("old")}, active="old")
    dispatcher = FakeCommandDispatcher()
    view = _view("cancel")
    session = _dirty_session()

    presenter = RecipesPresenter(
        store=store,
        view=view,
        commands=dispatcher,
        topology_session=session,
    )
    presenter._selected_slug = "cup"
    presenter.on_set_active()

    view.confirm_discard_changes.assert_called_once()
    assert dispatcher.dispatched == [], "cancel не должен диспатчить ActivateRecipe"
    assert store.get_active() == "old", "cancel не должен менять активный рецепт"
    assert session.dirty is True, "cancel сохраняет несохранённые правки"


# ---------------------------------------------------------------------------
# discard → активация происходит (правки теряются)
# ---------------------------------------------------------------------------


def test_activate_dirty_discard_activates() -> None:
    """dirty + «Не сохранять» → ActivateRecipe диспатчится, рецепт активирован."""
    store = FakeRecipeStore(raw={"cup": _recipe_raw("cup"), "old": _recipe_raw("old")}, active="old")
    dispatcher = FakeCommandDispatcher()
    view = _view("discard")
    session = _dirty_session()

    presenter = RecipesPresenter(
        store=store,
        view=view,
        commands=dispatcher,
        topology_session=session,
    )
    presenter._selected_slug = "cup"
    presenter.on_set_active()

    view.confirm_discard_changes.assert_called_once()
    activated = [c.slug for c in dispatcher.dispatched if isinstance(c, ActivateRecipe)]
    assert activated == ["cup"], "discard должен активировать выбранный рецепт"
    assert store.get_active() == "cup"


# ---------------------------------------------------------------------------
# save → правки пишутся в ПОКИДАЕМЫЙ рецепт, затем активация
# ---------------------------------------------------------------------------


def test_activate_dirty_save_persists_prev_then_activates() -> None:
    """dirty + «Сохранить» → on_save в текущий (old) рецепт, dirty снят, затем активация."""
    store = FakeRecipeStore(raw={"cup": _recipe_raw("cup"), "old": _recipe_raw("old")}, active="old")
    dispatcher = FakeCommandDispatcher()
    view = _view("save")
    session = _dirty_session()
    topology_store = FakeTopologyRepository(
        Topology.from_dict({"processes": [{"process_name": "edited", "plugins": []}], "wires": [], "displays": []})
    )

    presenter = RecipesPresenter(
        store=store,
        view=view,
        commands=dispatcher,
        topology_store=topology_store,
        topology_session=session,
    )
    presenter._selected_slug = "cup"
    presenter.on_set_active()

    # Правки сохранены в ПОКИДАЕМЫЙ рецепт (old), не в целевой (cup).
    saved_old = store.read_raw("old")
    assert saved_old["blueprint"]["processes"][0]["process_name"] == "edited"
    # on_save снял dirty; активация (RecipeActivated) в проде снимает оба — здесь
    # dispatcher фейковый и событий не шлёт, поэтому проверяем именно эффект on_save.
    assert session.dirty is False
    # Активация выбранного рецепта состоялась.
    activated = [c.slug for c in dispatcher.dispatched if isinstance(c, ActivateRecipe)]
    assert activated == ["cup"]
    assert store.get_active() == "cup"


# ---------------------------------------------------------------------------
# save провалился → активация прервана (правки не теряются)
# ---------------------------------------------------------------------------


def test_activate_dirty_save_failure_aborts() -> None:
    """dirty + «Сохранить», но сохранять некуда (нет topology_store) → активация прервана."""
    store = FakeRecipeStore(raw={"cup": _recipe_raw("cup"), "old": _recipe_raw("old")}, active="old")
    dispatcher = FakeCommandDispatcher()
    view = _view("save")
    session = _dirty_session()

    presenter = RecipesPresenter(
        store=store,
        view=view,
        commands=dispatcher,
        topology_store=None,  # on_save вернёт False (источник топологии недоступен)
        topology_session=session,
    )
    presenter._selected_slug = "cup"
    presenter.on_set_active()

    assert dispatcher.dispatched == [], "провал сохранения должен прервать активацию"
    assert store.get_active() == "old"
    assert session.dirty is True


def test_activate_dirty_save_without_active_recipe_aborts() -> None:
    """Fable #1: dirty + «Сохранить», но активного рецепта нет → громкая ошибка,
    активация НЕ происходит, правки не потеряны (раньше молча продолжалась активация)."""
    # active=None: свежий старт / после деактивации.
    store = FakeRecipeStore(raw={"cup": _recipe_raw("cup")}, active=None)
    dispatcher = FakeCommandDispatcher()
    view = _view("save")
    session = _dirty_session()
    topology_store = FakeTopologyRepository(
        Topology.from_dict({"processes": [{"process_name": "p", "plugins": []}], "wires": [], "displays": []})
    )

    presenter = RecipesPresenter(
        store=store,
        view=view,
        commands=dispatcher,
        topology_store=topology_store,
        topology_session=session,
    )
    presenter._selected_slug = "cup"
    presenter.on_set_active()

    view.show_error.assert_called()  # громкая ошибка «нет активного рецепта»
    assert dispatcher.dispatched == [], "без активного рецепта активация не должна происходить"
    assert session.dirty is True, "правки не потеряны"


def test_activate_dirty_save_validation_error_aborts() -> None:
    """dirty + «Сохранить», граф невалиден (дубли имён) → RS-5-валидация валит Save,
    активация НЕ происходит, ошибка показана, состояние сохранено (требование владельца)."""
    store = FakeRecipeStore(raw={"cup": _recipe_raw("cup"), "old": _recipe_raw("old")}, active="old")
    dispatcher = FakeCommandDispatcher()
    view = _view("save")
    session = _dirty_session()
    # Граф с дублирующимися именами процессов — validate_recipe_blueprint бросит
    # RecipeValidationError, on_save поймает → show_error + return False.
    topology_store = FakeTopologyRepository(
        Topology.from_dict(
            {
                "processes": [
                    {"process_name": "dup", "plugins": []},
                    {"process_name": "dup", "plugins": []},
                ],
                "wires": [],
                "displays": [],
            }
        )
    )

    presenter = RecipesPresenter(
        store=store,
        view=view,
        commands=dispatcher,
        topology_store=topology_store,
        topology_session=session,
    )
    presenter._selected_slug = "cup"
    presenter.on_set_active()

    view.show_error.assert_called()  # ошибка валидации показана
    assert dispatcher.dispatched == [], "провал валидации должен прервать активацию"
    assert store.get_active() == "old", "активный рецепт не сменён"
    assert session.dirty is True, "правки не потеряны"


# ---------------------------------------------------------------------------
# Характеризация: чистый путь (не dirty) — диалога нет, активация как раньше
# ---------------------------------------------------------------------------


def test_activate_clean_no_dialog() -> None:
    """Без несохранённых правок confirm_discard_changes НЕ вызывается (поведение до RS-4)."""
    store = FakeRecipeStore(raw={"cup": _recipe_raw("cup"), "old": _recipe_raw("old")}, active="old")
    dispatcher = FakeCommandDispatcher()
    view = _view("cancel")  # даже если бы вызвали — cancel; проверяем, что НЕ вызвали
    session = TopologySession()  # чистая: dirty=False

    presenter = RecipesPresenter(
        store=store,
        view=view,
        commands=dispatcher,
        topology_session=session,
    )
    presenter._selected_slug = "cup"
    presenter.on_set_active()

    view.confirm_discard_changes.assert_not_called()
    activated = [c.slug for c in dispatcher.dispatched if isinstance(c, ActivateRecipe)]
    assert activated == ["cup"]


def test_activate_without_session_no_dialog() -> None:
    """Без сессии (None) dirty-guard не работает — активация без диалога (backward compat)."""
    store = FakeRecipeStore(raw={"cup": _recipe_raw("cup"), "old": _recipe_raw("old")}, active="old")
    dispatcher = FakeCommandDispatcher()
    view = _view("cancel")

    presenter = RecipesPresenter(store=store, view=view, commands=dispatcher, topology_session=None)
    presenter._selected_slug = "cup"
    presenter.on_set_active()

    view.confirm_discard_changes.assert_not_called()
    assert store.get_active() == "cup"
