# -*- coding: utf-8 -*-
"""
Сборка v2 спинбокса: BindingConfig + SpinBoxConfig + SpinBoxControl.create.
"""
from __future__ import annotations

from typing import Optional, Union

from frontend_module.components._examples.spinbox.schemas import (
    ExampleSpinboxUiConfig,
    ExampleSpinboxValueRegister,
)
from frontend_module.components.base.config import BindingConfig
from frontend_module.components.base.interfaces import RegistersManagerLike
from frontend_module.components.spinbox import (
    SpinBoxConfig,
    SpinBoxControl,
    SpinBoxControlResult,
)


def spinbox_binding(access_level: int = 0) -> BindingConfig:
    return BindingConfig(
        register_name=ExampleSpinboxValueRegister.BINDING_REGISTER,
        field_name=ExampleSpinboxValueRegister.BINDING_FIELD,
        access_level=access_level,
    )


def spinbox_view_config_from_ui(ui: ExampleSpinboxUiConfig) -> SpinBoxConfig:
    label = ui.spinbox_label.strip() or None
    tooltip = ui.spinbox_tooltip.strip() or None
    return SpinBoxConfig(
        label=label,
        tooltip=tooltip,
        enabled=ui.spinbox_widget_enabled,
        min_val=ui.spinbox_min,
        max_val=ui.spinbox_max,
        label_position=ui.spinbox_position,
    )


def coerce_ui(
    ui: Optional[Union[ExampleSpinboxUiConfig, dict]],
) -> ExampleSpinboxUiConfig:
    if ui is None:
        return ExampleSpinboxUiConfig()
    if isinstance(ui, ExampleSpinboxUiConfig):
        return ui
    return ExampleSpinboxUiConfig.model_validate(ui)


def create_example_spinbox(
    registers_manager: Optional[RegistersManagerLike],
    ui: Optional[Union[ExampleSpinboxUiConfig, dict]] = None,
    *,
    access_level: int = 0,
) -> SpinBoxControlResult:
    return SpinBoxControl.create(
        registers_manager,
        spinbox_binding(access_level=access_level),
        spinbox_view_config_from_ui(coerce_ui(ui)),
        current_access_level=access_level,
    )
