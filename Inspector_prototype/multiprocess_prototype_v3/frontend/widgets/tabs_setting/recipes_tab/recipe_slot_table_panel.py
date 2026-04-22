# multiprocess_prototype_v3/frontend/widgets/tabs_setting/recipes_tab/recipe_slot_table_panel.py
"""Обратная совместимость имён: виджеты в recipes_widget / settings_recipe_widget."""

from ...settings_recipe_widget import AppRecipePanelWidget as AppRecipePanel
from ...recipes_widget import RegisterRecipePanelWidget as RegisterRecipePanel

__all__ = ["AppRecipePanel", "RegisterRecipePanel"]
