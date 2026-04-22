# -*- coding: utf-8 -*-
"""Тесты BindingConfig, SliderConfig, CheckboxViewConfig (control_v2)."""
from frontend_module.components import (
    BindingConfig,
    CheckboxViewConfig,
    SliderConfig,
)
from frontend_module.components.base.config import merge_config


class TestBindingConfig:
    def test_create(self) -> None:
        b = BindingConfig("processor", "min_area")
        assert b.register_name == "processor"
        assert b.field_name == "min_area"
        assert b.access_level == 0

    def test_with_index(self) -> None:
        b = BindingConfig("proc", "arr", index=1)
        assert b.index == 1


class TestSliderConfig:
    def test_defaults(self) -> None:
        cfg = SliderConfig()
        assert cfg.show_ticks is False
        assert cfg.label_position == "left"

    def test_label_override(self) -> None:
        cfg = SliderConfig(label="Test", min_val=0, max_val=100)
        lo = cfg.to_label_override()
        assert lo.label == "Test"
        assert lo.min_val == 0
        assert lo.max_val == 100


class TestCheckboxViewConfig:
    def test_defaults(self) -> None:
        cfg = CheckboxViewConfig()
        assert cfg.position == "left"

    def test_position_values(self) -> None:
        for pos in ("left", "right", "top", "bottom"):
            cfg = CheckboxViewConfig(position=pos)
            assert cfg.position == pos


class TestMergeConfig:
    def test_merge_overrides(self) -> None:
        base = SliderConfig(min_val=10.0, label="Base")
        over = SliderConfig(label="X")
        merged = merge_config(base, over)
        assert merged.label == "X"
        assert merged.min_val == 10.0
