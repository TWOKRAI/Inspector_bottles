"""recipe_engine.py — Доменный wrapper над generic-RecipeEngine из фреймворка.

Generic-реализация — `multiprocess_framework.modules.state_store_module.recipes.recipe_engine`.
Здесь добавляется автоматическое подключение доменных миграций v1 → v2
(см. `migrations/v1_to_v2.py`) через параметры migration_fn / migration_check_fn
(ADR-SS-003 в state_store_module/DECISIONS.md).
"""
from multiprocess_framework.modules.state_store_module.recipes.recipe_engine import (  # noqa: F401
    RecipeEngine as _RecipeEngine,
    DEFAULT_CONFIG_PATHS,
    _flatten,
    _remap_path,
    _set_nested,
)
from multiprocess_prototype.state_store.recipes.migrations import (
    migrate_recipe_data,
    needs_migration,
    RECIPE_VERSION_V2,
)


class RecipeEngine(_RecipeEngine):
    """Доменный wrapper: подключает migration_fn / migration_check_fn автоматически.

    Поведение совпадает с generic-`RecipeEngine`, но при создании без явного
    указания миграций используется доменный модуль `migrations.v1_to_v2`.
    """

    def __init__(self, store, recipes_dir, **kwargs):
        kwargs.setdefault("migration_fn", migrate_recipe_data)
        kwargs.setdefault("migration_check_fn", needs_migration)
        kwargs.setdefault("recipe_version", RECIPE_VERSION_V2)
        super().__init__(store, recipes_dir, **kwargs)


__all__ = ["RecipeEngine", "DEFAULT_CONFIG_PATHS"]
