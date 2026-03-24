# -*- coding: utf-8 -*-
"""
Сборка v2 slider из schemas: BindingConfig + SliderConfig + SliderControl.create.
"""
from __future__ import annotations

from typing import Optional, Union

from frontend_module.components.examples.slider.schemas import (
    ExampleSliderUiConfig,
    ExampleSliderValueRegister,
)
from frontend_module.components.base.config import BindingConfig
from frontend_module.components.base.interfaces import RegistersManagerLike
from frontend_module.components.slider import (
    SliderControl,
    SliderControlResult,
    SliderConfig,
)


def slider_binding(access_level: int = 0) -> BindingConfig:
    """BindingConfig из ClassVar на ExampleSliderValueRegister."""
    return BindingConfig(
        register_name=ExampleSliderValueRegister.BINDING_REGISTER,
        field_name=ExampleSliderValueRegister.BINDING_FIELD,
        access_level=access_level,
    )


def slider_view_config_from_ui(ui: ExampleSliderUiConfig) -> SliderConfig:
    """UI-схема → SliderConfig; пустой label → None (подпись из ResolvedMeta)."""
    label = ui.slider_label.strip() or None
    tooltip = ui.slider_tooltip.strip() or None
    return SliderConfig(
        label=label,
        tooltip=tooltip,
        enabled=ui.slider_widget_enabled,
        show_ticks=ui.slider_show_ticks,
        min_val=ui.slider_min,
        max_val=ui.slider_max,
        label_position=ui.slider_position,
    )


def coerce_ui(
    ui: Optional[Union[ExampleSliderUiConfig, dict]]
) -> ExampleSliderUiConfig:
    """None / dict / экземпляр → ExampleSliderUiConfig."""
    if ui is None:
        return ExampleSliderUiConfig()
    if isinstance(ui, ExampleSliderUiConfig):
        return ui
    return ExampleSliderUiConfig.model_validate(ui)


def create_example_slider(
    registers_manager: Optional[RegistersManagerLike],
    ui: Optional[Union[ExampleSliderUiConfig, dict]] = None,
    *,
    access_level: int = 0,
) -> SliderControlResult:
    """Один вызов: UI-схема + демо-binding → SliderControl.create."""
    return SliderControl.create(
        registers_manager,
        slider_binding(access_level=access_level),
        slider_view_config_from_ui(coerce_ui(ui)),
        current_access_level=access_level,
    )
