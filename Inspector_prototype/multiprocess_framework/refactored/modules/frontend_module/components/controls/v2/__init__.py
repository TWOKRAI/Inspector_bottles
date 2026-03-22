# -*- coding: utf-8 -*-
"""
Контролы v2 — архитектура Traits + Presenter + View + Facade.

Принцип конструктора: все компоненты — переиспользуемые «кубики» для сборки виджетов.
"""
from frontend_module.components.controls.v2.base.config import (
    BaseControlConfig,
    BindingConfig,
    merge_config,
)
from frontend_module.components.controls.v2.base.traits import LegacySyncContext
from frontend_module.components.controls.v2.checkbox import (
    CheckboxControl,
    CheckboxControlResult,
    CheckboxViewConfig,
    checkbox_left,
    checkbox_right,
)
from frontend_module.components.controls.v2.compound import (
    CompoundControl,
    CompoundControlConfig,
    CompoundControlResult,
    CompoundNumericConfig,
    CompoundNumericControl,
    CompoundNumericControlResult,
    ControlFactory,
)
from frontend_module.components.controls.v2.group import (
    GroupConfig,
    LabeledNumericGroupConfig,
    label_bgr_slider_default,
    label_slider_default,
    label_spinbox_default,
)
from frontend_module.components.controls.v2.label import LabelConfig
from frontend_module.components.controls.v2.slider import SliderConfig
from frontend_module.components.controls.v2.spinbox import SpinBoxConfig
from frontend_module.components.controls.v2.numeric import (
    NumericControl,
    NumericControlResult,
    NumericViewConfig,
    bgr_slider_default,
    slider_default,
    spinbox_default,
)

__all__ = [
    "NumericControl",
    "NumericControlResult",
    "CheckboxControl",
    "CheckboxControlResult",
    "CompoundNumericControl",
    "CompoundNumericControlResult",
    "CompoundControl",
    "CompoundControlResult",
    "ControlFactory",
    "LegacySyncContext",
    "BindingConfig",
    "NumericViewConfig",
    "CheckboxViewConfig",
    "CompoundNumericConfig",
    "CompoundControlConfig",
    "BaseControlConfig",
    "merge_config",
    "slider_default",
    "spinbox_default",
    "bgr_slider_default",
    "checkbox_left",
    "checkbox_right",
    "LabelConfig",
    "SliderConfig",
    "SpinBoxConfig",
    "GroupConfig",
    "LabeledNumericGroupConfig",
    "label_slider_default",
    "label_spinbox_default",
    "label_bgr_slider_default",
]
