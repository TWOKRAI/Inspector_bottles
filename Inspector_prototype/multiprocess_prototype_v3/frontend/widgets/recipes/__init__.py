"""Recipes widgets — рецепты регистрации, профили, слот-кнопки и панели настройки.

Реэкспорт Qt-классов — **ленивый** (через `__getattr__`), чтобы pure-Python тесты
могли импортировать `widgets.recipes` без поднятия PySide6.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover — только для type-checkers
    from .recipes_slot_buttons import RecipesSlotButtonsPanel
    from .recipes_widget import (
        RegisterRecipeModel,
        RegisterRecipePanelWidget,
        RegisterRecipePresenter,
    )
    from .settings_profile_widget import (
        SettingsProfilePanelWidget,
        SettingsProfileTabConfig,
    )
    from .settings_recipe_widget import (
        AppRecipeModel,
        AppRecipePanelWidget,
        AppRecipePresenter,
        RecipesTabConfig,
    )


_LAZY_ATTRS: dict[str, str] = {
    "RecipesSlotButtonsPanel": "recipes_slot_buttons",
    "RegisterRecipeModel": "recipes_widget",
    "RegisterRecipePanelWidget": "recipes_widget",
    "RegisterRecipePresenter": "recipes_widget",
    "SettingsProfilePanelWidget": "settings_profile_widget",
    "SettingsProfileTabConfig": "settings_profile_widget",
    "AppRecipeModel": "settings_recipe_widget",
    "AppRecipePanelWidget": "settings_recipe_widget",
    "AppRecipePresenter": "settings_recipe_widget",
    "RecipesTabConfig": "settings_recipe_widget",
}


def __getattr__(name: str) -> Any:
    submod_name = _LAZY_ATTRS.get(name)
    if submod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    mod = import_module(f".{submod_name}", package=__name__)
    return getattr(mod, name)


__all__ = sorted(_LAZY_ATTRS.keys())
