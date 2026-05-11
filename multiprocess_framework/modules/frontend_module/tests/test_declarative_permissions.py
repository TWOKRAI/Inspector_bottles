# -*- coding: utf-8 -*-
"""Тесты декларативных permissions в BaseControlConfig и presenter.set_access_context."""
from __future__ import annotations

import pytest

from multiprocess_framework.modules.frontend_module.components.base.config import (
    BaseControlConfig,
)
from multiprocess_framework.modules.frontend_module.components.base.traits.access_trait import (
    AccessTrait,
)
from multiprocess_framework.modules.frontend_module.managers.access_context import (
    AccessContext,
)


class TestBaseControlConfigPermissions:
    """Новые поля required_view_permission/required_edit_permission в BaseControlConfig."""

    def test_defaults_are_none(self):
        cfg = BaseControlConfig()
        assert cfg.required_view_permission is None
        assert cfg.required_edit_permission is None

    def test_explicit_values(self):
        cfg = BaseControlConfig(
            required_view_permission="tabs.recipes.view",
            required_edit_permission="tabs.recipes.edit",
        )
        assert cfg.required_view_permission == "tabs.recipes.view"
        assert cfg.required_edit_permission == "tabs.recipes.edit"


class TestAccessTraitWithContext:
    """AccessTrait применяет AccessContext через .update(ctx)."""

    def test_view_permission_required_grants_visibility(self):
        trait = AccessTrait(
            legacy_required_level=0,
            required_view_permission="tabs.recipes.view",
        )
        # Без permission — не виден
        trait.update(AccessContext())
        assert trait.can_view() is False
        # С permission — виден
        trait.update(
            AccessContext(permissions=frozenset({"tabs.recipes.view"}))
        )
        assert trait.can_view() is True

    def test_edit_permission_required_grants_modification(self):
        trait = AccessTrait(
            legacy_required_level=0,
            required_view_permission="tabs.recipes.view",
            required_edit_permission="tabs.recipes.edit",
        )
        # view есть, edit нет — read-only
        trait.update(
            AccessContext(permissions=frozenset({"tabs.recipes.view"}))
        )
        assert trait.can_view() is True
        assert trait.can_modify() is False
        # view + edit — полный доступ
        trait.update(
            AccessContext(
                permissions=frozenset(
                    {"tabs.recipes.view", "tabs.recipes.edit"}
                )
            )
        )
        assert trait.can_view() is True
        assert trait.can_modify() is True

    def test_coherence_no_view_implies_no_edit(self):
        trait = AccessTrait(
            legacy_required_level=0,
            required_view_permission="tabs.recipes.view",
            required_edit_permission="tabs.recipes.edit",
        )
        # Только edit без view — coherence запрещает modify
        trait.update(
            AccessContext(permissions=frozenset({"tabs.recipes.edit"}))
        )
        assert trait.can_view() is False
        assert trait.can_modify() is False

    def test_wildcard_grants_everything(self):
        trait = AccessTrait(
            legacy_required_level=0,
            required_view_permission="tabs.x.view",
            required_edit_permission="tabs.x.edit",
        )
        trait.update(
            AccessContext(permissions=frozenset({"*"}), role_name="dev")
        )
        assert trait.can_view() is True
        assert trait.can_modify() is True

    def test_legacy_path_no_perms_falls_back_to_level(self):
        """Без permission-полей AccessTrait использует числовой level."""
        trait = AccessTrait(legacy_required_level=5)
        trait.update(AccessContext(level=3))
        assert trait.can_modify() is False
        trait.update(AccessContext(level=5))
        assert trait.can_modify() is True
