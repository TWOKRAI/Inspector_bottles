"""Шим: RecipeEngine консолидирован в модуль `recipe` (C1, ADR-RCP-001).

Реализация переехала в `multiprocess_framework.modules.recipe.recipe_engine`.
Здесь — тонкий реэкспорт для обратной совместимости пути импорта
`state_store_module.recipes.recipe_engine` (используется прототипом и тестами).

Модуль `recipe` типизирует store через собственный `StoreProtocol` и НЕ импортирует
`state_store_module` — поэтому этот реэкспорт не создаёт цикла recipe ↔ state_store.

`_flatten`/`_remap_path` здесь раньше тоже реэкспортировались, но у реэкспорта не
было ни одного импортёра (AU-7, follow-up В1, 2026-07-12) — мёртвые приватные
хелперы, снят.
"""

from __future__ import annotations

from multiprocess_framework.modules.recipe.recipe_engine import RecipeEngine

__all__ = ["RecipeEngine"]
