# multiprocess_prototype_v3/frontend/widgets/settings_recipe_widget/model.py
"""Модель панели app-рецептов."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from multiprocess_prototype_v3.managers.access_context import AccessContext
from multiprocess_prototype_v3.managers.recipe_manager_protocol import RecipeManagerProtocol

from .schemas import RecipesTabConfig


@dataclass
class AppRecipeModel:
    """Рецепты UI-схем (агрегат SchemaBase)."""

    ui: RecipesTabConfig
    recipes_tab_dict: Dict[str, Any]
    processing_tab_ui_dict: Dict[str, Any]
    recipe_manager: Optional[RecipeManagerProtocol]
    access_ctx: AccessContext
    app_aggregate: Dict[str, Any] = field(default_factory=dict)

    def compute_initial_slot(self) -> int:
        """Слот из recipe_manager (текущий app-рецепт) или нижняя граница из UI."""
        mgr = self.recipe_manager
        if mgr is not None and hasattr(mgr, "get_current_app_recipe_number"):
            try:
                return int(mgr.get_current_app_recipe_number())
            except (TypeError, ValueError):
                pass
        u = self.ui
        return max(u.recipe_index_min, min(u.recipe_index_max, u.recipe_index_min))
