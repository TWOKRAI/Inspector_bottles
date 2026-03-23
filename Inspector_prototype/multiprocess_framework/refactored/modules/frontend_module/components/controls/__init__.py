# -*- coding: utf-8 -*-
"""
Shim: re-export control_v2 для обратной совместимости.

frontend_module.components.controls → frontend_module.components.control_v2
"""
from frontend_module.components.control_v2 import (
    BindingConfig,
    CheckboxControl,
    CheckboxViewConfig,
    NumericControl,
    NumericViewConfig,
    SliderConfig,
)

# Alias: legacy components.controls used CheckboxConfig
CheckboxConfig = CheckboxViewConfig

__all__ = [
    "BindingConfig",
    "CheckboxConfig",
    "CheckboxControl",
    "CheckboxViewConfig",
    "NumericControl",
    "NumericViewConfig",
    "SliderConfig",
]
