"""manager.py — шим над `recipe.RecipeManager` (консолидация C3, ADR-RCP-005).

Прежде здесь жил доменный субкласс, инжектировавший comment-preserving writer
(`yaml_io.update_yaml_preserving`) в duplicate() — seam до переезда yaml_io во
фреймворк. Теперь writer generic и живёт в самом модуле `recipe`, а базовый
`RecipeManager` использует его по умолчанию — субкласс-шим больше не нужен.

Здесь — тонкий реэкспорт для обратной совместимости пути импорта
`multiprocess_prototype.recipes.manager` (его импортируют recipe_store,
frontend/app, presenter рецептов).
"""

from __future__ import annotations

from multiprocess_framework.modules.recipe.manager import RecipeManager

__all__ = ["RecipeManager"]
