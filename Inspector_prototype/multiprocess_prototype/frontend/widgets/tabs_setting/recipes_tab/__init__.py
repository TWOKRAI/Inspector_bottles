# multiprocess_prototype/frontend/widgets/tabs_setting/recipes_tab/
"""
Вкладка рецептов: слот, загрузка/сохранение снимка, таблица полей регистров.

Экспорты:
- RecipesTabWidget — виджет вкладки
- RecipesTabConfig — подписи и параметры UI
"""

from .schemas import RecipesTabConfig
from .recipe_slot_table_panel import AppRecipePanel, RecipeSlotTablePanel, RegisterRecipePanel
from .widget import RecipesTabWidget

__all__ = [
    "AppRecipePanel",
    "RecipeSlotTablePanel",
    "RecipesTabConfig",
    "RecipesTabWidget",
    "RegisterRecipePanel",
]
