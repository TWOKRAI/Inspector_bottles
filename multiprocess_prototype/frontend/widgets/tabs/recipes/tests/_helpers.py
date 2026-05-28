# -*- coding: utf-8 -*-
"""Вспомогательные фабрики для recipes-тестов (Task E.3 → F.4).

make_recipes_services() — builder поверх make_test_app_services().
Task F.4: presenter работает через RecipeStore Protocol напрямую (без _rm bridge).
"""

from __future__ import annotations

from multiprocess_prototype.domain.app_services import AppServices
from multiprocess_prototype.domain.tests._fakes import FakeRecipeStore
from multiprocess_prototype.domain.tests.conftest import make_test_app_services


def make_recipes_services(
    *,
    recipes: FakeRecipeStore | None = None,
    raw: dict[str, dict] | None = None,
    active: str | None = None,
) -> AppServices:
    """Создать AppServices для recipes-тестов.

    Args:
        recipes: готовый FakeRecipeStore. Если None — создаётся из raw/active.
        raw: начальные raw-dict рецепты для FakeRecipeStore.
        active: slug активного рецепта.
    """
    if recipes is None:
        recipes = FakeRecipeStore(raw=raw, active=active)
    return make_test_app_services(recipes=recipes)


__all__ = ["make_recipes_services"]
