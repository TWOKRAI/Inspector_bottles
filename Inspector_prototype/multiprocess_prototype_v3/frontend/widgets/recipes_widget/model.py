# multiprocess_prototype_v3/frontend/widgets/recipes_widget/model.py
"""Модель панели рецептов регистров."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from frontend_module.interfaces import IRegistersManagerGui

from multiprocess_prototype_v3.managers.access_context import AccessContext
from multiprocess_prototype_v3.managers.recipe_manager_protocol import RecipeManagerProtocol

from ..settings_recipe_widget.schemas import RecipesTabConfig


@dataclass
class RegisterRecipeModel:
    """Рецепты регистров: снимок полей через RegistersManager."""

    rm: IRegistersManagerGui
    recipe_manager: Optional[RecipeManagerProtocol]
    access_ctx: AccessContext
    ui: RecipesTabConfig
    on_recipe_applied: Optional[Callable[[int], None]] = None
    on_recipe_saved: Optional[Callable[[int], None]] = None

    def compute_initial_slot(self) -> int:
        """Текущий слот из recipe_manager (register или legacy API) или границы UI."""
        mgr = self.recipe_manager
        if mgr is not None and hasattr(mgr, "get_current_register_recipe_number"):
            try:
                return int(mgr.get_current_register_recipe_number())
            except (TypeError, ValueError):
                pass
        if mgr is not None and hasattr(mgr, "get_current_recipe_number"):
            try:
                return int(mgr.get_current_recipe_number())
            except (TypeError, ValueError):
                pass
        u = self.ui
        return max(u.recipe_index_min, min(u.recipe_index_max, u.recipe_index_min))
