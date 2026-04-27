# multiprocess_prototype_v3/frontend/widgets/recipes_widget/
"""Изолированный виджет: панель рецептов регистров (BaseWidget + MVP).

Публичный API доступен через import, но Qt-зависимые сущности
(`RegisterRecipePanelWidget`, `RegisterRecipePresenter`, `RegisterRecipeModel`)
подгружаются лениво — это позволяет тестировать pure-Python ядро
(`RecipeSlotComboModel`, `recipe_rows`, `RecipeSlotComboModel`) без PySide6.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .auto_save import AutoSaveConfig, RecipeAutoSave
from .recipe_rows import (
    build_recipe_rows,
    coerce_string_to_value,
    format_value_for_cell,
    scalar_for_editing,
)
from .slot_combo_model import RecipeSlotComboModel

if TYPE_CHECKING:  # pragma: no cover — только для type-checkers
    from .model import RegisterRecipeModel
    from .panel_widget import RegisterRecipePanelWidget
    from .presenter import RegisterRecipePresenter


_LAZY_ATTRS = {
    "RegisterRecipeModel": ("model", "RegisterRecipeModel"),
    "RegisterRecipePanelWidget": ("panel_widget", "RegisterRecipePanelWidget"),
    "RegisterRecipePresenter": ("presenter", "RegisterRecipePresenter"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_ATTRS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = target
    from importlib import import_module

    mod = import_module(f".{module_name}", package=__name__)
    return getattr(mod, attr)


__all__ = [
    "AutoSaveConfig",
    "RegisterRecipeModel",
    "RegisterRecipePanelWidget",
    "RegisterRecipePresenter",
    "RecipeAutoSave",
    "RecipeSlotComboModel",
    "build_recipe_rows",
    "coerce_string_to_value",
    "format_value_for_cell",
    "scalar_for_editing",
]
