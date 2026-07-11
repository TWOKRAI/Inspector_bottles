"""recipe_engine.py — доменный шим над generic-RecipeEngine из модуля `recipe`.

Generic-реализация — `multiprocess_framework.modules.recipe.recipe_engine`
(консолидация C1, ADR-RCP-001). Прежде generic-движок жил в
`state_store_module.recipes` — теперь это тонкий реэкспорт того же класса.

Доменная надстройка здесь:

1. Автоматическое подключение доменных миграций v1 → v2 (см. `migrations/v1_to_v2.py`)
   через параметры migration_fn / migration_check_fn (ADR-SS-003).
2. Инъекция доменных ветвей snapshot по умолчанию (`DEFAULT_CONFIG_PATHS`) через
   параметр default_paths (ADR-RCP-001) — фреймворк доменных ветвей не несёт.

Отвязка v3-рецептов от legacy-движка (fix recipe-v3-engine-decouple) теперь
реализована generic-ветвью в базовом `RecipeEngine.load()` (detect.is_v3_recipe):
v3-blueprint помечается active без migrate/replay/перезаписи файла. Доменному шиму
переопределять load() больше не нужно.
"""

from __future__ import annotations

from multiprocess_framework.modules.recipe.recipe_engine import RecipeEngine as _RecipeEngine
from multiprocess_prototype.backend.state.recipes.migrations import (
    RECIPE_VERSION_V2,
    migrate_recipe_data,
    needs_migration,
)
from multiprocess_prototype.backend.state.recipes.migrations.v1_to_v2 import DOC_TYPE

# Доменные ветви Inspector, снимаемые save(paths=None). Раньше — зашитая константа
# фреймворка; теперь домен несёт прикладной слой и инжектирует её в движок.
DEFAULT_CONFIG_PATHS: list[str] = [
    "cameras",  # cameras.*.config + cameras.*.regions
    "renderer",  # renderer.config
    "robot",  # robot.config
    "database",  # database.config
]


class RecipeEngine(_RecipeEngine):
    """Доменный шим: подключает миграции v1→v2 и доменные default_paths.

    Поведение совпадает с generic-`RecipeEngine`; при создании без явного указания
    используются доменный модуль `migrations.v1_to_v2` и `DEFAULT_CONFIG_PATHS`.
    """

    def __init__(self, store, recipes_dir, **kwargs):
        kwargs.setdefault("migration_fn", migrate_recipe_data)
        kwargs.setdefault("migration_check_fn", needs_migration)
        kwargs.setdefault("recipe_version", RECIPE_VERSION_V2)
        kwargs.setdefault("default_paths", DEFAULT_CONFIG_PATHS)
        # doc_type реестра миграций (C3): здесь migration_fn инжектирован явно и
        # приоритетен (поведение бит-в-бит), но doc_type документирует связь с
        # реестром и включает дефолтный run_chain, если инъекцию когда-то уберут.
        kwargs.setdefault("doc_type", DOC_TYPE)
        super().__init__(store, recipes_dir, **kwargs)


__all__ = ["RecipeEngine", "DEFAULT_CONFIG_PATHS"]
