# -*- coding: utf-8 -*-
"""format.py — шим над `recipe.format` (консолидация C1, ADR-RCP-001).

Единая нормализация raw-рецепта v3 на запись переехала в
`multiprocess_framework.modules.recipe.format`. Здесь — тонкий реэкспорт для
обратной совместимости пути импорта `multiprocess_prototype.recipes.format`.
"""

from __future__ import annotations

from multiprocess_framework.modules.recipe.format import normalize_recipe_v3_raw

__all__ = ["normalize_recipe_v3_raw"]
