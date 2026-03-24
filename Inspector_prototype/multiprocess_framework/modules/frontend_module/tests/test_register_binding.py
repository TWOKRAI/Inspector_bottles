# -*- coding: utf-8 -*-
"""Тесты RegisterBinding, RegisterFieldMeta, ResolvedMeta."""
import pytest

from frontend_module.schemas.register_binding import (
    RegisterBinding,
    RegisterFieldMeta,
    ResolvedMeta,
)


class TestRegisterBinding:
    def test_parse_simple(self) -> None:
        b = RegisterBinding.parse("dp")
        assert b.register_name == ""
        assert b.field_name == "dp"

    def test_parse_dotted(self) -> None:
        b = RegisterBinding.parse("processor.min_area")
        assert b.register_name == "processor"
        assert b.field_name == "min_area"


class TestRegisterFieldMeta:
    def test_from_dict_empty(self) -> None:
        m = RegisterFieldMeta.from_dict({})
        assert m.min is None
        assert m.max is None
        assert m.default is None
        assert m.unit == ""

    def test_from_dict_full(self) -> None:
        m = RegisterFieldMeta.from_dict({
            "min": 10,
            "max": 5000,
            "default": 500,
            "unit": "px",
            "info": "Минимальная площадь",
            "transfer_k": 1.0,
            "round_k": 0,
        })
        assert m.min == 10
        assert m.max == 5000
        assert m.default == 500
        assert m.unit == "px"
        assert m.transfer_k == 1.0
        assert m.round_k == 0


class TestResolvedMeta:
    def test_merge_defaults(self) -> None:
        meta = RegisterFieldMeta.from_dict({"min": 0, "max": 100, "info": "Value"})
        resolved = ResolvedMeta.merge(meta, {}, "field_x")
        assert resolved.label == "Value"
        assert resolved.min_val == 0
        assert resolved.max_val == 100
        assert resolved.transfer_k == 1.0
        assert resolved.round_k == 0

    def test_merge_config_overrides(self) -> None:
        meta = RegisterFieldMeta.from_dict({
            "min": 10,
            "max": 5000,
            "default": 500,
            "info": "Area",
            "transfer_k": 0.5,
        })
        config = {"label": "Custom label", "transfer_k": 2.0}
        resolved = ResolvedMeta.merge(meta, config, "min_area")
        assert resolved.label == "Custom label"
        assert resolved.transfer_k == 2.0
        assert resolved.min_val == 10
        assert resolved.max_val == 5000
