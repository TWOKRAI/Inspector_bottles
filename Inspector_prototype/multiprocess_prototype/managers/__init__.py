# multiprocess_prototype/managers/
"""Прикладные менеджеры прототипа (рецепты и др.)."""

from .access_context import AccessContext
from .recipe_manager import DEFAULT_RECIPE_SLOT_ID, RecipeManager
from .recipe_manager_protocol import RecipeManagerProtocol

__all__ = ["AccessContext", "DEFAULT_RECIPE_SLOT_ID", "RecipeManager", "RecipeManagerProtocol"]
