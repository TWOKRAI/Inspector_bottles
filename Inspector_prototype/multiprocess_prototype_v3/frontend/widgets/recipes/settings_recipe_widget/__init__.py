# multiprocess_prototype_v3/frontend/widgets/settings_recipe_widget/
"""Изолированный виджет: панель app-рецептов (BaseWidget + MVP)."""

from .model import AppRecipeModel
from .panel_widget import AppRecipePanelWidget
from .presenter import AppRecipePresenter
from .schemas import RecipesTabConfig, default_tab_item

__all__ = [
    "AppRecipeModel",
    "AppRecipePanelWidget",
    "AppRecipePresenter",
    "RecipesTabConfig",
    "default_tab_item",
]
