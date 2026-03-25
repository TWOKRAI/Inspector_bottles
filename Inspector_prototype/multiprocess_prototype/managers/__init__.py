# multiprocess_prototype/managers/
"""Прикладные менеджеры прототипа (рецепты и др.)."""

from .access_context import AccessContext
from .recipe_manager import RecipeManager
from .recipe_manager_protocol import RecipeManagerProtocol

__all__ = ["AccessContext", "RecipeManager", "RecipeManagerProtocol"]
