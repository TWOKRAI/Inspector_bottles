"""Application-level managers."""

from .recipe_manager import DEFAULT_RECIPE_SLOT_ID, RecipeManager
from .recipe_manager_protocol import RecipeManagerProtocol

__all__ = [
    "DEFAULT_RECIPE_SLOT_ID",
    "RecipeManager",
    "RecipeManagerProtocol",
]
