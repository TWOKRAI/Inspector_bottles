# -*- coding: utf-8 -*-
"""
Сборка ``NumericControl`` из UI-схемы и ``ExampleNumericValueRegister``.
"""
from __future__ import annotations

from typing import Optional, Union

from frontend_module.components.base.config import BindingConfig
from frontend_module.components.base.interfaces import RegistersManagerLike
from frontend_module.components.examples.numeric.schemas import (
    ExampleNumericUiConfig,
    ExampleNumericValueRegister,
)
from frontend_module.components.numeric import (
    NumericControl,
    NumericControlResult,
)
from frontend_module.components.numeric.config import NumericViewConfig


def numeric_binding(access_level: int = 0) -> BindingConfig:
    return BindingConfig(
        register_name=ExampleNumericValueRegister.BINDING_REGISTER,
        field_name=ExampleNumericValueRegister.BINDING_FIELD,
        access_level=access_level,
    )


def numeric_view_config_from_ui(ui: ExampleNumericUiConfig) -> NumericViewConfig:
    label = ui.numeric_label.strip() or None
    tooltip = ui.numeric_tooltip.strip() or None
    return NumericViewConfig(
        view_type=ui.numeric_view_type,
        label=label,
        tooltip=tooltip,
        enabled=ui.numeric_widget_enabled,
        show_ticks=ui.numeric_show_ticks,
        min_val=ui.numeric_min,
        max_val=ui.numeric_max,
        label_position=ui.numeric_position,
    )


def coerce_ui(
    ui: Optional[Union[ExampleNumericUiConfig, dict]],
) -> ExampleNumericUiConfig:
    if ui is None:
        return ExampleNumericUiConfig()
    if isinstance(ui, ExampleNumericUiConfig):
        return ui
    return ExampleNumericUiConfig.model_validate(ui)


def create_example_numeric(
    registers_manager: Optional[RegistersManagerLike],
    ui: Optional[Union[ExampleNumericUiConfig, dict]] = None,
    *,
    access_level: int = 0,
) -> NumericControlResult:
    u = coerce_ui(ui)
    return NumericControl.create(
        registers_manager,
        numeric_binding(access_level=access_level),
        numeric_view_config_from_ui(u),
        current_access_level=access_level,
    )
