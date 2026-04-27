# multiprocess_prototype_v3/frontend/widgets/tabs_setting/recipes_tab/
"""
Вкладка «Рецепты»: только оболочка (скролл, placeholder).

Фиче-виджеты: recipes_widget, settings_recipe_widget; общая схема: settings_recipe_widget.schemas.
"""

from ...recipes.settings_recipe_widget.schemas import RecipesTabConfig
from ...recipes.settings_recipe_widget import AppRecipePanelWidget
from ...recipes.recipes_widget import RegisterRecipePanelWidget
from .recipe_slot_table_panel import AppRecipePanel, RegisterRecipePanel
from .widget import RecipesTabWidget

__all__ = [
    "AppRecipePanel",
    "AppRecipePanelWidget",
    "RecipesTabConfig",
    "RecipesTabWidget",
    "RegisterRecipePanel",
    "RegisterRecipePanelWidget",
]
