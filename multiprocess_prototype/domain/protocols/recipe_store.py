# -*- coding: utf-8 -*-
"""
domain/protocols/recipe_store.py — Protocol для доступа к рецептам.

RecipeStore предоставляет ДВА уровня доступа:
  1. Recipe entity (денормализованный вид) — read/write для domain-логики.
  2. Raw dict (исходная YAML-структура) — read_raw/save_raw для blueprint-persistence,
     где presenter'ам нужна полная YAML-структура (data/blueprint/display_bindings/
     gui_positions/version/name/description).

Phase C создал адаптер RecipeStoreFromManager поверх существующего RecipeManager.
Phase F расширил Protocol: + read_raw/save_raw/duplicate/deactivate, set_active -> bool.
"""

from __future__ import annotations

from typing import Protocol

from ..entities.recipe import Recipe


class RecipeStore(Protocol):
    """Контракт доступа к рецептам (entity + raw dict).

    Реализации: RecipeStoreFromManager (adapter), FakeRecipeStore (тесты).
    """

    def list(self) -> tuple[str, ...]:
        """Вернуть список slug'ов всех доступных рецептов."""
        ...

    def read(self, slug: str) -> Recipe | None:
        """Прочитать рецепт по slug как Recipe entity. Возвращает None если не найден."""
        ...

    def write(self, slug: str, recipe: Recipe) -> None:
        """Сохранить рецепт по slug (создать или перезаписать) — денормализованный формат."""
        ...

    def delete(self, slug: str) -> None:
        """Удалить рецепт по slug."""
        ...

    def get_active(self) -> str | None:
        """Вернуть slug активного рецепта или None."""
        ...

    def set_active(self, slug: str | None) -> bool:
        """Установить активный рецепт. slug=None сбрасывает (через deactivate). Вернуть True при успехе."""
        ...

    def deactivate(self) -> None:
        """Сбросить активный рецепт."""
        ...

    def duplicate(self, slug: str, new_slug: str) -> bool:
        """Дублировать рецепт. True если успех, False при ошибке."""
        ...

    def read_raw(self, slug: str) -> dict | None:
        """Прочитать raw YAML dict (полная структура). None если не найден."""
        ...

    def save_raw(self, slug: str, data: dict) -> None:
        """Записать raw dict в YAML-файл рецепта."""
        ...


__all__ = [
    "RecipeStore",
]
