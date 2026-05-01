"""state_store.recipes — доменный wrapper над generic-RecipeEngine.

RecipeEngine из этого пакета автоматически подключает доменные миграции
v1 → v2 (`migrations/v1_to_v2.py`) через параметры migration_fn /
migration_check_fn (ADR-SS-003 в state_store_module/DECISIONS.md).
"""
from multiprocess_prototype.state_store.recipes.recipe_engine import RecipeEngine

__all__ = ["RecipeEngine"]
