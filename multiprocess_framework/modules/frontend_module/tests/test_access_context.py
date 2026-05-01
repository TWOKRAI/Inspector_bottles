"""Тесты AccessContext."""
from __future__ import annotations

import pytest

from multiprocess_framework.modules.frontend_module.managers.access_context import AccessContext


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
