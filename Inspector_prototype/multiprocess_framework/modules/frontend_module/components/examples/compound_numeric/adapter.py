# -*- coding: utf-8 -*-
"""
Сборка ``CompoundNumericControl`` из UI-схемы и ``ExampleBgrTripletRegister``.
"""
from __future__ import annotations

from typing import Optional, Union

from frontend_module.components.examples.compound_numeric.schemas import (
    ExampleBgrTripletRegister,
    ExampleCompoundNumericUiConfig,
)
from frontend_module.components.base.config import BindingConfig
from frontend_module.components.base.interfaces import RegistersManagerLike
from frontend_module.components.compound.facade import (
    CompoundNumericControl,
    CompoundNumericControlResult,
)
from frontend_module.components.compound.config import CompoundNumericConfig
from frontend_module.components.numeric.config import NumericViewConfig


def compound_numeric_binding(access_level: int = 0) -> BindingConfig:
    return BindingConfig(
        register_name=ExampleBgrTripletRegister.BINDING_REGISTER,
        field_name=ExampleBgrTripletRegister.BINDING_FIELD,
        access_level=access_level,
    )


def compound_numeric_view_config_from_ui(
    ui: ExampleCompoundNumericUiConfig,
) -> NumericViewConfig:
    return NumericViewConfig(
        view_type=ui.numeric_view_type,
        show_ticks=ui.show_ticks,
        enabled=ui.channel_widget_enabled,
        min_val=ui.channel_min,
        max_val=ui.channel_max,
        label_position=ui.label_position,
    )


def coerce_ui(
    ui: Optional[Union[ExampleCompoundNumericUiConfig, dict]],
) -> ExampleCompoundNumericUiConfig:
    if ui is None:
        return ExampleCompoundNumericUiConfig()
    if isinstance(ui, ExampleCompoundNumericUiConfig):
        return ui
    return ExampleCompoundNumericUiConfig.model_validate(ui)


def create_example_compound_numeric(
    registers_manager: Optional[RegistersManagerLike],
    ui: Optional[Union[ExampleCompoundNumericUiConfig, dict]] = None,
    *,
    access_level: int = 0,
) -> CompoundNumericControlResult:
    u = coerce_ui(ui)
    labels = [u.label_b.strip() or "B", u.label_g.strip() or "G", u.label_r.strip() or "R"]
    base = compound_numeric_binding(access_level=access_level)
    child_vc = compound_numeric_view_config_from_ui(u)
    config = CompoundNumericConfig(
        binding=base,
        labels=labels,
        view_config=child_vc,
    )
    return CompoundNumericControl.create(
        registers_manager,
        config,
        current_access_level=access_level,
    )
