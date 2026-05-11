"""Тесты AccessContext."""
from __future__ import annotations

import pytest

from multiprocess_framework.modules.frontend_module.managers.access_context import AccessContext


# ===========================================================================
# Оригинальные тесты (не изменены — PR1-Group-C backward compat)
# ===========================================================================

class TestAccessContextDefaults:
    def test_default_level_zero(self):
        ctx = AccessContext()
        assert ctx.level == 0

    def test_default_bypass_readonly_false(self):
        ctx = AccessContext()
        assert ctx.bypass_readonly is False

    def test_default_show_hidden_false(self):
        ctx = AccessContext()
        assert ctx.show_hidden is False

    def test_is_frozen(self):
        ctx = AccessContext(level=1)
        with pytest.raises((AttributeError, TypeError)):
            ctx.level = 2


class TestAccessContextFromDict:
    def test_from_dict_none_returns_default(self):
        ctx = AccessContext.from_dict(None)
        assert ctx.level == 0
        assert ctx.bypass_readonly is False
        assert ctx.show_hidden is False

    def test_from_dict_empty_returns_default(self):
        ctx = AccessContext.from_dict({})
        assert ctx.level == 0

    def test_from_dict_full(self):
        ctx = AccessContext.from_dict({
            "level": 3,
            "bypass_readonly": True,
            "show_hidden": True,
        })
        assert ctx.level == 3
        assert ctx.bypass_readonly is True
        assert ctx.show_hidden is True

    def test_from_dict_partial(self):
        ctx = AccessContext.from_dict({"level": 5})
        assert ctx.level == 5
        assert ctx.bypass_readonly is False

    def test_from_dict_coerces_types(self):
        ctx = AccessContext.from_dict({"level": "2", "bypass_readonly": 1})
        assert ctx.level == 2
        assert ctx.bypass_readonly is True

    def test_equality(self):
        a = AccessContext.from_dict({"level": 1})
        b = AccessContext(level=1)
        assert a == b

    def test_hash_consistency(self):
        a = AccessContext(level=1, bypass_readonly=True)
        b = AccessContext(level=1, bypass_readonly=True)
        assert hash(a) == hash(b)

    def test_different_instances_not_equal(self):
        a = AccessContext(level=1)
        b = AccessContext(level=2)
        assert a != b


# ===========================================================================
# Новые тесты PR1-Group-C: permissions, role_name, has_permission, to_dict
# ===========================================================================

class TestAccessContextPermissions:
    def test_default_permissions_empty_frozenset(self):
        ctx = AccessContext()
        assert ctx.permissions == frozenset()

    def test_default_role_name_empty_string(self):
        ctx = AccessContext()
        assert ctx.role_name == ""

    def test_has_permission_present(self):
        ctx = AccessContext(permissions=frozenset({"tabs.recipes.view", "tabs.recipes.edit"}))
        assert ctx.has_permission("tabs.recipes.view") is True

    def test_has_permission_absent(self):
        ctx = AccessContext(permissions=frozenset({"tabs.recipes.view"}))
        assert ctx.has_permission("tabs.recipes.edit") is False

    def test_has_permission_empty_set(self):
        ctx = AccessContext()
        assert ctx.has_permission("any.perm") is False

    def test_permissions_immutable_frozenset(self):
        ctx = AccessContext(permissions=frozenset({"a", "b"}))
        # frozenset не имеет add
        assert not hasattr(ctx.permissions, "add")

    def test_backward_compat_level_only(self):
        """AccessContext(level=5) без permissions — работает, permissions=frozenset()."""
        ctx = AccessContext(level=5)
        assert ctx.level == 5
        assert ctx.permissions == frozenset()
        assert ctx.role_name == ""

    def test_positional_args_backward_compat(self):
        """AccessContext(5, True, True) — позиционные аргументы продолжают работать."""
        ctx = AccessContext(5, True, True)
        assert ctx.level == 5
        assert ctx.bypass_readonly is True
        assert ctx.show_hidden is True
        assert ctx.permissions == frozenset()


class TestAccessContextFromDictNew:
    def test_from_dict_with_permissions_list(self):
        ctx = AccessContext.from_dict({"permissions": ["a", "b"]})
        assert ctx.permissions == frozenset({"a", "b"})

    def test_from_dict_with_permissions_empty_list(self):
        ctx = AccessContext.from_dict({"permissions": []})
        assert ctx.permissions == frozenset()

    def test_from_dict_empty_dict_permissions_default(self):
        ctx = AccessContext.from_dict({})
        assert ctx.permissions == frozenset()
        assert ctx.role_name == ""

    def test_from_dict_none_permissions_default(self):
        ctx = AccessContext.from_dict(None)
        assert ctx.permissions == frozenset()
        assert ctx.role_name == ""

    def test_from_dict_with_role_name(self):
        ctx = AccessContext.from_dict({"role_name": "admin"})
        assert ctx.role_name == "admin"

    def test_from_dict_full_new(self):
        ctx = AccessContext.from_dict({
            "level": 3,
            "bypass_readonly": True,
            "show_hidden": False,
            "permissions": ["tabs.view", "tabs.edit"],
            "role_name": "operator",
        })
        assert ctx.level == 3
        assert ctx.bypass_readonly is True
        assert ctx.permissions == frozenset({"tabs.view", "tabs.edit"})
        assert ctx.role_name == "operator"


class TestAccessContextToDict:
    def test_to_dict_basic(self):
        ctx = AccessContext(level=1, bypass_readonly=False, show_hidden=True)
        d = ctx.to_dict()
        assert d["level"] == 1
        assert d["bypass_readonly"] is False
        assert d["show_hidden"] is True
        assert d["permissions"] == []
        assert d["role_name"] == ""

    def test_to_dict_permissions_sorted_list(self):
        ctx = AccessContext(permissions=frozenset({"b", "a", "c"}))
        d = ctx.to_dict()
        assert d["permissions"] == ["a", "b", "c"]

    def test_round_trip(self):
        """AccessContext → to_dict() → from_dict() → исходный объект."""
        original = AccessContext(
            level=5,
            bypass_readonly=True,
            show_hidden=False,
            permissions=frozenset({"x.view", "x.edit"}),
            role_name="admin",
        )
        d = original.to_dict()
        restored = AccessContext.from_dict(d)
        assert restored == original

    def test_round_trip_empty(self):
        """Пустой AccessContext выживает round-trip."""
        ctx = AccessContext()
        assert AccessContext.from_dict(ctx.to_dict()) == ctx


class TestAccessContextHashingNew:
    def test_equal_contexts_same_hash(self):
        """Два AccessContext с одинаковыми полями равны и имеют одинаковый hash."""
        a = AccessContext(level=2, permissions=frozenset({"p1"}), role_name="r")
        b = AccessContext(level=2, permissions=frozenset({"p1"}), role_name="r")
        assert a == b
        assert hash(a) == hash(b)

    def test_different_permissions_not_equal(self):
        a = AccessContext(permissions=frozenset({"p1"}))
        b = AccessContext(permissions=frozenset({"p2"}))
        assert a != b

    def test_usable_as_dict_key(self):
        """AccessContext можно использовать как ключ dict (hashable)."""
        ctx = AccessContext(level=1, permissions=frozenset({"x"}))
        d = {ctx: "value"}
        assert d[ctx] == "value"
