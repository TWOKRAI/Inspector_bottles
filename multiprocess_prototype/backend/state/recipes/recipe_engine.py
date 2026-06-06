"""recipe_engine.py — Доменный wrapper над generic-RecipeEngine из фреймворка.

Generic-реализация — `multiprocess_framework.modules.state_store_module.recipes.recipe_engine`.
Здесь добавляется:

1. Автоматическое подключение доменных миграций v1 → v2 (см. `migrations/v1_to_v2.py`)
   через параметры migration_fn / migration_check_fn (ADR-SS-003 в state_store_module/DECISIONS.md).
2. **Отвязка v3-рецептов от legacy-движка** (fix recipe-v3-engine-decouple).

Почему (2): generic `RecipeEngine.load()` рассчитан на config-snapshot с envelope
``{meta: {version}, data: {...}}`` — он реплеит ``data`` в TreeStore и при устаревшей
версии переписывает файл миграцией. Рецепты прототипа — формат **v3**: плоский
top-level ``{name, version, blueprint, ...}`` без envelope ``data``. Для такого файла
движок видел ``data={}`` и отсутствие ``meta.version`` (→ version=1 < recipe_version),
считал его legacy и ПЕРЕЗАПИСЫВАЛ миграцией пустого ``data``, затирая ``blueprint`` и
комментарии (баг: при каждом ``set_active`` рецепт превращался в мусор
``meta:{migrated_from_v1}`` + ``data:{пустой blueprint}``).

v3-рецепт — это топология-blueprint, которую запускает recipe-driven backend, а НЕ
config-snapshot для TreeStore. Поэтому ``load()`` для v3 не делает ни migrate, ни
TreeStore-replay, ни перезаписи файла — только помечает рецепт активным.
"""

from __future__ import annotations

from typing import Any

import yaml

from multiprocess_framework.modules.state_store_module.recipes.recipe_engine import (
    RecipeEngine as _RecipeEngine,
    DEFAULT_CONFIG_PATHS,
)
from multiprocess_prototype.backend.state.recipes.migrations import (
    migrate_recipe_data,
    needs_migration,
    RECIPE_VERSION_V2,
)


class RecipeEngine(_RecipeEngine):
    """Доменный wrapper: подключает миграции v1→v2 и отвязывает v3 от legacy-load.

    Поведение совпадает с generic-`RecipeEngine`, но:
    - при создании без явного указания миграций используется доменный модуль
      `migrations.v1_to_v2`;
    - `load()` для v3-рецептов (top-level `blueprint`) короткозамыкается без
      migrate/TreeStore-replay/перезаписи файла (см. модульный docstring).
    """

    def __init__(self, store, recipes_dir, **kwargs):
        kwargs.setdefault("migration_fn", migrate_recipe_data)
        kwargs.setdefault("migration_check_fn", needs_migration)
        kwargs.setdefault("recipe_version", RECIPE_VERSION_V2)
        super().__init__(store, recipes_dir, **kwargs)

    # ------------------------------------------------------------------
    # v3-detection
    # ------------------------------------------------------------------

    @staticmethod
    def _is_v3_recipe(recipe: Any) -> bool:
        """True если файл — рецепт формата v3 (top-level blueprint / version >= 3).

        Маркер v3 — наличие ключа ``blueprint`` на верхнем уровне (плоский формат
        без envelope ``data``). Дополнительно ``version >= 3`` как явная отметка.
        Битый файл (blueprint + остаточные data/meta от прошлой порчи) тоже
        распознаётся как v3 по наличию ``blueprint`` — повторной порчи не будет.
        """
        if not isinstance(recipe, dict):
            return False
        if "blueprint" in recipe:
            return True
        version = recipe.get("version")
        return isinstance(version, int) and version >= 3

    # ------------------------------------------------------------------
    # load (override)
    # ------------------------------------------------------------------

    def load(self, name: str, remap: dict[str, str] | None = None) -> list:
        """Загрузить рецепт. v3 — без legacy migrate/replay/перезаписи (см. docstring).

        Для v3 только помечает рецепт активным (``_active_name``) и возвращает пустой
        список дельт. Для legacy config-snapshot (envelope ``data``/``meta``) —
        делегирует в generic `RecipeEngine.load()` (миграция + TreeStore-replay).
        """
        file_path = self._recipes_dir / f"{name}.yaml"
        if not file_path.exists():
            raise FileNotFoundError(f"Рецепт не найден: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            recipe = yaml.safe_load(f)

        if self._is_v3_recipe(recipe):
            # v3-blueprint: топологию запускает recipe-driven backend, не TreeStore.
            # Ни migrate, ни replay, ни write — только пометка active.
            self._active_name = name
            self._loaded_paths = None
            self._loaded_snapshot = None
            return []

        return super().load(name, remap)


__all__ = ["RecipeEngine", "DEFAULT_CONFIG_PATHS"]
