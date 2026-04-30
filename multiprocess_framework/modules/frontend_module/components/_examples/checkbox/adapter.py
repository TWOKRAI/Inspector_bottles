# -*- coding: utf-8 -*-
"""
Сборка v2 checkbox из schemas: BindingConfig + CheckboxViewConfig + CheckboxControl.create.
"""
from __future__ import annotations

from typing import Optional, Union

from multiprocess_framework.modules.frontend_module.components._examples.checkbox.schemas import (
    ExampleCheckboxUiConfig,
    ExampleCheckboxValueRegister,
)
from multiprocess_framework.modules.frontend_module.components.base.config import BindingConfig
from multiprocess_framework.modules.frontend_module.components.base.interfaces import RegistersManagerLike
from multiprocess_framework.modules.frontend_module.components.checkbox import (
    CheckboxControl,
    CheckboxControlResult,
    CheckboxViewConfig,
)


def checkbox_binding(access_level: int = 0) -> BindingConfig:
    """`BindingConfig` из `ClassVar` на `ExampleCheckboxValueRegister`."""
    return BindingConfig(
        register_name=ExampleCheckboxValueRegister.BINDING_REGISTER,
        field_name=ExampleCheckboxValueRegister.BINDING_FIELD,
        access_level=access_level,
    )


def checkbox_view_config_from_ui(ui: ExampleCheckboxUiConfig) -> CheckboxViewConfig:
    """UI-схема → dataclass v2; пустой label → `None` (подпись из `ResolvedMeta`)."""
    label = ui.checkbox_label.strip() or None
    tooltip = ui.checkbox_tooltip.strip() or None
    return CheckboxViewConfig(
        label=label,
        tooltip=tooltip,
        enabled=ui.checkbox_widget_enabled,
        position=ui.checkbox_position,
    )


def coerce_ui(ui: Optional[Union[ExampleCheckboxUiConfig, dict]]) -> ExampleCheckboxUiConfig:
    """``None`` / dict / экземпляр → `ExampleCheckboxUiConfig`."""
    if ui is None:
        return ExampleCheckboxUiConfig()
    if isinstance(ui, ExampleCheckboxUiConfig):
        return ui
    return ExampleCheckboxUiConfig.model_validate(ui)


def create_example_checkbox(
    registers_manager: Optional[RegistersManagerLike],
    ui: Optional[Union[ExampleCheckboxUiConfig, dict]] = None,
    *,
    access_level: int = 0,
) -> CheckboxControlResult:
    """Один вызов: UI-схема + демо-binding → `CheckboxControl.create`."""
    return CheckboxControl.create(
        registers_manager,
        checkbox_binding(access_level=access_level),
        checkbox_view_config_from_ui(coerce_ui(ui)),
        current_access_level=access_level,
    )
