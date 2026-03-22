# -*- coding: utf-8 -*-
"""
Публичный вход пакета controls.

- v1: SliderControl, CheckboxControl (наследуют BaseConfigurableWidget)
- v2: NumericControl, CheckboxControl (Traits + Presenter + View + Facade)

Подробности структуры — в ``README.md``, архитектура v2 — в ``v2/README.md``.
"""
from frontend_module.components.controls.slider import (
    SliderConfig,
    SliderControl,
    SliderRegisterExample,
)
from frontend_module.components.controls.checkbox import (
    CheckboxConfig,
    CheckboxControl as CheckboxControlV1,
    CheckboxRegisterExample,
)
CheckboxControl = CheckboxControlV1  # v2 overwrites when available
try:
    from frontend_module.components.controls.v2 import (
        BaseControlConfig,
        BindingConfig,
        CheckboxControl,
        CheckboxControlResult,
        CheckboxViewConfig,
        CompoundControl,
        CompoundControlConfig,
        CompoundControlResult,
        CompoundNumericConfig,
        CompoundNumericControl,
        CompoundNumericControlResult,
        ControlFactory,
        LegacySyncContext,
        NumericControl,
        NumericControlResult,
        NumericViewConfig,
        merge_config,
        bgr_slider_default,
        checkbox_left,
        checkbox_right,
        slider_default,
        spinbox_default,
    )
    _V2_AVAILABLE = True
except ImportError:
    _V2_AVAILABLE = False
    BaseControlConfig = None  # type: ignore
    BindingConfig = None  # type: ignore
    CheckboxControl = None  # type: ignore
    CheckboxControlResult = None  # type: ignore
    CheckboxViewConfig = None  # type: ignore
    CompoundControl = None  # type: ignore
    CompoundControlConfig = None  # type: ignore
    CompoundControlResult = None  # type: ignore
    CompoundNumericConfig = None  # type: ignore
    CompoundNumericControl = None  # type: ignore
    CompoundNumericControlResult = None  # type: ignore
    ControlFactory = None  # type: ignore
    LegacySyncContext = None  # type: ignore
    NumericControl = None  # type: ignore
    NumericControlResult = None  # type: ignore
    NumericViewConfig = None  # type: ignore
    merge_config = None  # type: ignore
    bgr_slider_default = None  # type: ignore
    checkbox_left = None  # type: ignore
    checkbox_right = None  # type: ignore
    slider_default = None  # type: ignore
    spinbox_default = None  # type: ignore

__all__ = [
    "SliderControl",
    "SliderConfig",
    "SliderRegisterExample",
    "CheckboxControl",
    "CheckboxControlV1",  # v1 fallback when v2 unavailable
    "CheckboxConfig",
    "CheckboxRegisterExample",
]
if _V2_AVAILABLE:
    __all__ += [
        "NumericControl",
        "NumericControlResult",
        "CheckboxControl",
        "CheckboxControlResult",
        "CompoundNumericControl",
        "CompoundNumericControlResult",
        "CompoundNumericConfig",
        "CompoundControl",
        "CompoundControlResult",
        "CompoundControlConfig",
        "ControlFactory",
        "LegacySyncContext",
        "BindingConfig",
        "NumericViewConfig",
        "CheckboxViewConfig",
        "BaseControlConfig",
        "merge_config",
        "slider_default",
        "spinbox_default",
        "bgr_slider_default",
        "checkbox_left",
        "checkbox_right",
    ]
