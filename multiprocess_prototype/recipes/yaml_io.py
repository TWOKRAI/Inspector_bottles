# -*- coding: utf-8 -*-
"""yaml_io.py — шим над `recipe.yaml_io` (консолидация C3, ADR-RCP-005).

Generic comment-preserving writer (ruamel round-trip) переехал во фреймворк —
`multiprocess_framework.modules.recipe.yaml_io`. Здесь — тонкий реэкспорт для
обратной совместимости пути импорта `multiprocess_prototype.recipes.yaml_io`
(его импортируют recipe_store, launch, frontend/app, миграции).
"""

from __future__ import annotations

from multiprocess_framework.modules.recipe.yaml_io import (
    update_blueprint_metadata_preserving,
    update_yaml_preserving,
)

__all__ = ["update_yaml_preserving", "update_blueprint_metadata_preserving"]
