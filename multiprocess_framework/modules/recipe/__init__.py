"""recipe — управление рецептами (snapshot config-ветвей, detect, миграции, CRUD).

Крыша фреймворка над рецептами. Generic-механизмы; доменные пути и миграции
инжектируются прикладным слоем (ADR-SS-003, ADR-SS-011, ADR-RCP-001).

Публичный API — только через этот модуль и `interfaces.py`.
"""

from .detect import is_v3_recipe
from .format import normalize_recipe_v3_raw
from .interfaces import (
    RecipeEngineProtocol,
    RecipeManagerProtocol,
    StoreProtocol,
)
from .manager import RecipeManager
from .recipe_engine import RecipeEngine

__all__ = [
    "RecipeEngine",
    "RecipeManager",
    "is_v3_recipe",
    "normalize_recipe_v3_raw",
    "StoreProtocol",
    "RecipeEngineProtocol",
    "RecipeManagerProtocol",
]
