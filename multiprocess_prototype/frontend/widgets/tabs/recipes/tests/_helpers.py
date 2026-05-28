# -*- coding: utf-8 -*-
"""Вспомогательные фабрики для recipes-тестов (Task E.3).

make_recipes_services() — builder поверх make_test_app_services(), навешивающий
legacy RecipeManager на FakeRecipeStore через _rm bridge (RecipeStore Protocol
не покрывает богатый API: read_recipe→dict, duplicate, recipes_dir).
"""

from __future__ import annotations

from typing import Any

from multiprocess_prototype.domain.app_services import AppServices
from multiprocess_prototype.domain.tests._fakes import FakeRecipeStore
from multiprocess_prototype.domain.tests.conftest import make_test_app_services


def make_recipes_services(*, recipe_manager: Any = None) -> AppServices:
    """Создать AppServices для recipes-тестов.

    Args:
        recipe_manager: legacy RecipeManager (mock/fake). Навешивается на
            FakeRecipeStore как `_rm` bridge. Если None — таб уйдёт в
            "RecipeManager недоступен" путь.
    """
    recipes = FakeRecipeStore()
    if recipe_manager is not None:
        recipes._rm = recipe_manager  # type: ignore[attr-defined]
    return make_test_app_services(recipes=recipes)


__all__ = ["make_recipes_services"]
