# -*- coding: utf-8 -*-
"""Тесты coerce_schema_config."""
from frontend_module.components.controls.checkbox.schema import CheckboxConfig
from frontend_module.components.controls.slider.schema import SliderConfig
from frontend_module.core.schema_config import coerce_schema_config


class TestCoerceSchemaConfig:
    def test_none_returns_defaults_slider(self) -> None:
        cfg = coerce_schema_config(None, SliderConfig)
        assert cfg.register_name is None
        assert cfg.field_name is None

    def test_instance_unchanged(self) -> None:
        original = SliderConfig(register_name="r", field_name="f")
        cfg = coerce_schema_config(original, SliderConfig)
        assert cfg is original

    def test_dict_validates(self) -> None:
        cfg = coerce_schema_config(
            {"register_name": "proc", "field_name": "x", "label": "L"},
            SliderConfig,
        )
        assert cfg.register_name == "proc"
        assert cfg.field_name == "x"
        assert cfg.label == "L"

    def test_checkbox_dict(self) -> None:
        cfg = coerce_schema_config(
            {"register_name": "r", "field_name": "b", "position": "right"},
            CheckboxConfig,
        )
        assert cfg.position == "right"
