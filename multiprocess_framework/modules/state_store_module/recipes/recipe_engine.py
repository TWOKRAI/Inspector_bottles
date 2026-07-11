"""Шим: RecipeEngine консолидирован в модуль `recipe` (C1, ADR-RCP-001).

Реализация переехала в `multiprocess_framework.modules.recipe.recipe_engine`.
Здесь — тонкий реэкспорт для обратной совместимости пути импорта
`state_store_module.recipes.recipe_engine` (используется прототипом и тестами).

Модуль `recipe` типизирует store через собственный `StoreProtocol` и НЕ импортирует
`state_store_module` — поэтому этот реэкспорт не создаёт цикла recipe ↔ state_store.
"""

from __future__ import annotations

from multiprocess_framework.modules.recipe.recipe_engine import (
    RecipeEngine,
    _flatten,
    _remap_path,
)

__all__ = ["RecipeEngine", "_flatten", "_remap_path"]
