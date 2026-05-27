# -*- coding: utf-8 -*-
"""
domain/protocols/recipe_store.py — Protocol для CRUD-доступа к рецептам.

RecipeStore — минимальный контракт для работы с Recipe entities.
Domain работает исключительно с Recipe entity (не с raw-dict).
Phase C создаст адаптер RecipeManagerAdapter поверх существующего RecipeManager.
"""

from __future__ import annotations

from typing import Protocol

from ..entities.recipe import Recipe


class RecipeStore(Protocol):
    """Контракт CRUD-доступа к рецептам.

    Реализации: RecipeManagerAdapter (Phase C), _FakeRecipeStore (тесты).
    """

    def list(self) -> tuple[str, ...]:
        """Вернуть список slug'ов всех доступных рецептов."""
        ...

    def read(self, slug: str) -> Recipe | None:
        """Прочитать рецепт по slug. Возвращает None если не найден."""
        ...

    def write(self, slug: str, recipe: Recipe) -> None:
        """Сохранить рецепт по slug (создать или перезаписать)."""
        ...

    def delete(self, slug: str) -> None:
        """Удалить рецепт по slug."""
        ...

    def get_active(self) -> str | None:
        """Вернуть slug активного рецепта или None."""
        ...

    def set_active(self, slug: str | None) -> None:
        """Установить активный рецепт. slug=None сбрасывает активный."""
        ...


__all__ = [
    "RecipeStore",
]
