# -*- coding: utf-8 -*-
"""DEPRECATED: Тесты slot-based API RecipesPresenter (Phase 11, legacy).

Весь slot-based API (save_to_slot, apply_recipe, recipe_io) удалён в Task 5.7.
Файл сохранён как исторический артефакт и помечен skip.
Тесты TopologyHolder перенесены в test_topology_holder.py если потребуются.

Refs: plans/prototype-skeleton-2026-05/phase-5-recipes-manager-v2.md Task 5.7
"""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.skip(
    reason=(
        "Slot-based RecipesPresenter API удалён в Task 5.7. "
        "recipe_io.py удалён. "
        "Новые тесты — в test_recipes_tab.py и test_recipes_presenter.py."
    )
)


class TestTopologyHolder:
    """Placeholder: тесты TopologyHolder перенесены в соответствующий файл."""

    def test_placeholder(self) -> None:
        pass


class TestRecipesPresenterApply:
    """Placeholder: slot-based API удалён."""

    def test_placeholder(self) -> None:
        pass
