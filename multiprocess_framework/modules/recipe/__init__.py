"""recipe — управление рецептами (snapshot config-ветвей, detect, миграции, CRUD).

Крыша фреймворка над рецептами. Generic-механизмы; доменные пути и миграции
инжектируются прикладным слоем (ADR-SS-003, ADR-SS-011, ADR-RCP-001).

Публичный API — только через этот модуль и `interfaces.py`.
"""

from .detect import has_top_level_blueprint, is_v3_recipe, nested_blueprint_data
from .format import normalize_recipe_v3_raw
from .interfaces import (
    RecipeEngineProtocol,
    RecipeManagerProtocol,
    StoreProtocol,
)
from .manager import RecipeManager
from .migrations import migration, registered_steps, run_chain
from .recipe_engine import RecipeEngine

__all__ = [
    "RecipeEngine",
    "RecipeManager",
    "is_v3_recipe",
    "has_top_level_blueprint",
    "nested_blueprint_data",
    "normalize_recipe_v3_raw",
    "migration",
    "registered_steps",
    "run_chain",
    "StoreProtocol",
    "RecipeEngineProtocol",
    "RecipeManagerProtocol",
]
