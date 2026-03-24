# -*- coding: utf-8 -*-
"""
Сборка ``CompoundControl`` с ``items``: чекбокс + числовой слайдер.
"""
from __future__ import annotations

from typing import Optional, Union

from frontend_module.components.base.config import BindingConfig
from frontend_module.components.examples.compound_mixed.schemas import (
    ExampleCompoundMixedUiConfig,
    ExampleMixedBoolRegister,
    ExampleMixedFloatRegister,
)
from frontend_module.components.base.interfaces import RegistersManagerLike
from frontend_module.components.checkbox.config import CheckboxViewConfig
from frontend_module.components.compound.config import CompoundControlConfig
from frontend_module.components.compound.facade import (
    CompoundControl,
    CompoundControlResult,
)
from frontend_module.components.numeric.config import NumericViewConfig


def _strip_or_none(s: str) -> str | None:
    t = (s or "").strip()
    return t or None


def coerce_ui(
    ui: Optional[Union[ExampleCompoundMixedUiConfig, dict]],
) -> ExampleCompoundMixedUiConfig:
    if ui is None:
        return ExampleCompoundMixedUiConfig()
    if isinstance(ui, ExampleCompoundMixedUiConfig):
        return ui
    return ExampleCompoundMixedUiConfig.model_validate(ui)


def create_example_compound_mixed(
    registers_manager: Optional[RegistersManagerLike],
    ui: Optional[Union[ExampleCompoundMixedUiConfig, dict]] = None,
    *,
    access_level: int = 0,
) -> CompoundControlResult:
    u = coerce_ui(ui)
    items = [
        (
            BindingConfig(
                register_name=ExampleMixedBoolRegister.BINDING_REGISTER,
                field_name=ExampleMixedBoolRegister.BINDING_FIELD,
                access_level=access_level,
            ),
            CheckboxViewConfig(
                label=_strip_or_none(u.mix_checkbox_label),
                tooltip=_strip_or_none(u.mix_checkbox_tooltip),
                enabled=u.mix_checkbox_widget_enabled,
                position=u.mix_checkbox_position,
            ),
        ),
        (
            BindingConfig(
                register_name=ExampleMixedFloatRegister.BINDING_REGISTER,
                field_name=ExampleMixedFloatRegister.BINDING_FIELD,
                access_level=access_level,
            ),
            NumericViewConfig(
                view_type="slider",
                label=_strip_or_none(u.mix_slider_label),
                tooltip=_strip_or_none(u.mix_slider_tooltip),
                enabled=u.mix_slider_widget_enabled,
                show_ticks=u.mix_slider_show_ticks,
                label_position=u.mix_slider_position,
            ),
        ),
    ]
    config = CompoundControlConfig(
        orientation=u.compound_orientation,
        spacing=u.compound_spacing,
        items=items,
    )
    return CompoundControl.create(
        registers_manager,
        config,
        current_access_level=access_level,
    )
