# -*- coding: utf-8 -*-
"""Тесты SliderConfig, CheckboxConfig."""
import pytest

from frontend_module.components.controls.slider import SliderConfig
from frontend_module.components.controls.checkbox import CheckboxConfig


class TestSliderConfig:
    def test_defaults(self) -> None:
        cfg = SliderConfig()
        assert cfg.register_name is None
        assert cfg.field_name is None
        assert cfg.access_level == 0
        assert cfg.label is None
        assert cfg.transfer_k is None
        assert cfg.round_k is None

    def test_model_validate_dict(self) -> None:
        cfg = SliderConfig.model_validate({
            "register_name": "processor",
            "field_name": "min_area",
            "label": "Параметр",
            "transfer_k": 0.1,
        })
        assert cfg.register_name == "processor"
        assert cfg.field_name == "min_area"
        assert cfg.label == "Параметр"
        assert cfg.transfer_k == 0.1
        assert cfg.round_k is None

    def test_model_dump(self) -> None:
        cfg = SliderConfig(
            register_name="draw",
            field_name="dp",
            label="Test",
            transfer_k=2.0,
        )
        d = cfg.model_dump()
        assert d["register_name"] == "draw"
        assert d["field_name"] == "dp"
        assert d["label"] == "Test"
        assert d["transfer_k"] == 2.0


class TestCheckboxConfig:
    def test_defaults(self) -> None:
        cfg = CheckboxConfig()
        assert cfg.register_name is None
        assert cfg.field_name is None
        assert cfg.access_level == 0
        assert cfg.label is None
        assert cfg.position == "left"

    def test_model_validate_dict(self) -> None:
        cfg = CheckboxConfig.model_validate({
            "register_name": "renderer",
            "field_name": "show_mask",
            "label": "Mask",
            "position": "right",
        })
        assert cfg.register_name == "renderer"
        assert cfg.field_name == "show_mask"
        assert cfg.label == "Mask"
        assert cfg.position == "right"

    def test_position_values(self) -> None:
        for pos in ("left", "right", "top", "bottom"):
            cfg = CheckboxConfig(position=pos)
            assert cfg.position == pos
