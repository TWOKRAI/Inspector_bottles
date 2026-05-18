# -*- coding: utf-8 -*-
"""
Сборка combo из schemas: BindingConfig + ComboViewConfig + ComboControl.create.
"""

from __future__ import annotations

from typing import Optional, Union

from multiprocess_framework.modules.frontend_module.components._examples.combo.schemas import (
    ExampleComboUiConfig,
    ExampleComboValueRegister,
)
from multiprocess_framework.modules.frontend_module.components.base.config import BindingConfig
from multiprocess_framework.modules.frontend_module.components.base.interfaces import RegistersManagerLike
from multiprocess_framework.modules.frontend_module.components.combo import (
    ComboControl,
    ComboControlResult,
    ComboViewConfig,
)


def combo_binding(access_level: int = 0) -> BindingConfig:
    """`BindingConfig` из `ClassVar` на `ExampleComboValueRegister`."""
    return BindingConfig(
        register_name=ExampleComboValueRegister.BINDING_REGISTER,
        field_name=ExampleComboValueRegister.BINDING_FIELD,
        access_level=access_level,
    )


def combo_view_config_from_ui(ui: ExampleComboUiConfig) -> ComboViewConfig:
    """UI-схема → dataclass v2; пустой label → `None` (подпись из `ResolvedMeta`)."""
    label = ui.combo_label.strip() or None
    tooltip = ui.combo_tooltip.strip() or None
    return ComboViewConfig(
        label=label,
        tooltip=tooltip,
        enabled=ui.combo_widget_enabled,
        placeholder=ui.combo_placeholder,
    )


def coerce_ui(ui: Optional[Union[ExampleComboUiConfig, dict]]) -> ExampleComboUiConfig:
    """``None`` / dict / экземпляр → `ExampleComboUiConfig`."""
    if ui is None:
        return ExampleComboUiConfig()
    if isinstance(ui, ExampleComboUiConfig):
        return ui
    return ExampleComboUiConfig.model_validate(ui)


def create_example_combo(
    registers_manager: Optional[RegistersManagerLike],
    ui: Optional[Union[ExampleComboUiConfig, dict]] = None,
    *,
    access_level: int = 0,
) -> ComboControlResult:
    """Один вызов: UI-схема + демо-binding → `ComboControl.create`."""
    return ComboControl.create(
        registers_manager,
        combo_binding(access_level=access_level),
        combo_view_config_from_ui(coerce_ui(ui)),
        items=["auto", "manual", "off"],
        current_access_level=access_level,
    )
