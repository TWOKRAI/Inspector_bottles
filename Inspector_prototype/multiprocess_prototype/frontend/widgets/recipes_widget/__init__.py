# multiprocess_prototype/frontend/widgets/recipes_widget/
"""Изолированный виджет: панель рецептов регистров (BaseWidget + MVP)."""

from .panel_widget import RegisterRecipePanelWidget
from .presenter import RegisterRecipePresenter
from .model import RegisterRecipeModel
from .recipe_rows import build_recipe_rows, coerce_string_to_value, format_value_for_cell, scalar_for_editing

__all__ = [
    "RegisterRecipeModel",
    "RegisterRecipePanelWidget",
    "RegisterRecipePresenter",
    "build_recipe_rows",
    "coerce_string_to_value",
    "format_value_for_cell",
    "scalar_for_editing",
]
