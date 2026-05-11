# -*- coding: utf-8 -*-
"""
Тесты AccessTrait — двухосевая модель view/edit + legacy fallback.

PR1-Group-C: новый файл. Покрывает:
- legacy API (required_level kwarg, update(int))
- новый API (required_view_permission, required_edit_permission)
- coherence invariant: edit ⇒ view
- bypass_readonly через AccessContext
- DeprecationWarning для устаревших вызовов
"""
from __future__ import annotations

import warnings

import pytest

from multiprocess_framework.modules.frontend_module.components.base.traits.access_trait import AccessTrait
from multiprocess_framework.modules.frontend_module.managers.access_context import AccessContext


# ===========================================================================
# Legacy API
# ===========================================================================

class TestAccessTraitLegacy:
    def test_legacy_required_level_positional_no_warning(self):
        """AccessTrait(5) — позиционный вызов без warning."""
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            trait = AccessTrait(5)
        assert trait is not None

    def test_legacy_required_level_kwarg_no_warning(self):
        """AccessTrait(legacy_required_level=5) — без DeprecationWarning."""
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            trait = AccessTrait(legacy_required_level=5)
        assert trait is not None

    def test_old_required_level_kwarg_raises_deprecation_warning(self):
        """AccessTrait(required_level=5) — должен выдать DeprecationWarning."""
        with pytest.warns(DeprecationWarning, match="required_level"):
            trait = AccessTrait(required_level=5)
        # но работает корректно
        trait.update(AccessContext(level=5))
        assert trait.can_modify() is True

    def test_old_required_level_kwarg_works_after_warning(self):
        """После DeprecationWarning трейт с required_level работает как legacy_required_level."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            trait = AccessTrait(required_level=3)
        trait.update(AccessContext(level=2))
        assert trait.can_modify() is False
        trait.update(AccessContext(level=3))
        assert trait.can_modify() is True

    def test_update_with_int_raises_deprecation(self):
        """update(int) → DeprecationWarning."""
        trait = AccessTrait(legacy_required_level=2)
        with pytest.warns(DeprecationWarning, match="update"):
            trait.update(3)
        assert trait.can_modify() is True

    def test_update_with_int_legacy_path_works(self):
        """update(int) создаёт минимальный AccessContext с level=N."""
        trait = AccessTrait(legacy_required_level=5)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            trait.update(5)
        assert trait.can_modify() is True

    def test_can_modify_legacy_level_insufficient(self):
        """Legacy: level < required → can_modify False."""
        trait = AccessTrait(legacy_required_level=5)
        trait.update(AccessContext(level=4))
        assert trait.can_modify() is False

    def test_can_modify_legacy_level_exact(self):
        """Legacy: level == required → can_modify True."""
        trait = AccessTrait(legacy_required_level=5)
        trait.update(AccessContext(level=5))
        assert trait.can_modify() is True

    def test_set_required_level(self):
        """set_required_level изменяет порог."""
        trait = AccessTrait(legacy_required_level=2)
        trait.update(AccessContext(level=3))
        assert trait.can_modify() is True
        trait.set_required_level(5)
        assert trait.can_modify() is False
        trait.update(AccessContext(level=5))
        assert trait.can_modify() is True


# ===========================================================================
# Новый API: view/edit permissions
# ===========================================================================

class TestAccessTraitViewEditPermissions:
    def test_no_view_perm_can_view_always_true(self):
        """Без required_view_permission — can_view всегда True."""
        trait = AccessTrait()
        trait.update(AccessContext())
        assert trait.can_view() is True

    def test_view_perm_ctx_has_perm(self):
        """required_view_permission задан, ctx содержит perm → can_view True."""
        trait = AccessTrait(required_view_permission="tabs.view")
        trait.update(AccessContext(permissions=frozenset({"tabs.view"})))
        assert trait.can_view() is True

    def test_view_perm_ctx_missing_perm(self):
        """required_view_permission задан, ctx НЕ содержит perm → can_view False."""
        trait = AccessTrait(required_view_permission="tabs.view")
        trait.update(AccessContext(permissions=frozenset()))
        assert trait.can_view() is False

    def test_edit_perm_ctx_has_both(self):
        """Оба permission заданы, ctx содержит оба → can_view и can_modify True."""
        trait = AccessTrait(
            required_view_permission="tabs.view",
            required_edit_permission="tabs.edit",
        )
        trait.update(AccessContext(permissions=frozenset({"tabs.view", "tabs.edit"})))
        assert trait.can_view() is True
        assert trait.can_modify() is True

    def test_edit_perm_ctx_has_only_view(self):
        """ctx содержит только view perm → can_modify False."""
        trait = AccessTrait(
            required_view_permission="tabs.view",
            required_edit_permission="tabs.edit",
        )
        trait.update(AccessContext(permissions=frozenset({"tabs.view"})))
        assert trait.can_view() is True
        assert trait.can_modify() is False

    def test_edit_perm_ctx_has_only_edit_no_view_perm_required(self):
        """Только edit_perm задан (view_perm не задан) — can_view True, can_modify зависит от perm."""
        trait = AccessTrait(required_edit_permission="tabs.edit")
        trait.update(AccessContext(permissions=frozenset({"tabs.edit"})))
        assert trait.can_view() is True
        assert trait.can_modify() is True

    def test_coherence_no_view_implies_no_edit(self):
        """Coherence invariant: can_view == False → can_modify == False."""
        trait = AccessTrait(
            required_view_permission="tabs.view",
            required_edit_permission="tabs.edit",
        )
        # ctx имеет edit, но НЕ имеет view
        trait.update(AccessContext(permissions=frozenset({"tabs.edit"})))
        assert trait.can_view() is False
        assert trait.can_modify() is False  # edit ⇒ view нарушен, возвращаем False

    def test_empty_permissions_view_perm_required_can_view_false(self):
        """Пустой permission set + view_perm задан → can_view False."""
        trait = AccessTrait(required_view_permission="any.perm")
        trait.update(AccessContext(permissions=frozenset()))
        assert trait.can_view() is False


# ===========================================================================
# bypass_readonly
# ===========================================================================

class TestAccessTraitBypassReadonly:
    def test_bypass_readonly_allows_modify_despite_low_level(self):
        """bypass_readonly=True → can_modify True независимо от level (legacy fallback)."""
        trait = AccessTrait(legacy_required_level=10)
        trait.update(AccessContext(level=0, bypass_readonly=True))
        assert trait.can_modify() is True

    def test_bypass_readonly_does_not_bypass_edit_permission(self):
        """bypass_readonly НЕ обходит permission-check — только legacy level."""
        trait = AccessTrait(
            required_view_permission="tabs.view",
            required_edit_permission="tabs.edit",
        )
        # ctx имеет bypass_readonly и view perm, но НЕ edit perm
        ctx = AccessContext(
            bypass_readonly=True,
            permissions=frozenset({"tabs.view"}),
        )
        trait.update(ctx)
        assert trait.can_view() is True
        assert trait.can_modify() is False  # bypass_readonly не помогает при permission-mode


# ===========================================================================
# update(AccessContext) — новый путь
# ===========================================================================

class TestAccessTraitUpdateContext:
    def test_update_with_access_context_no_warning(self):
        """update(AccessContext) не вызывает DeprecationWarning."""
        trait = AccessTrait(legacy_required_level=1)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            trait.update(AccessContext(level=2))
        assert trait.can_modify() is True

    def test_update_replaces_context(self):
        """Последовательные update() заменяют контекст."""
        trait = AccessTrait(legacy_required_level=5)
        trait.update(AccessContext(level=5))
        assert trait.can_modify() is True
        trait.update(AccessContext(level=0))
        assert trait.can_modify() is False
