# -*- coding: utf-8 -*-
"""Числовые контролы v2 — фасад NumericControl (Slider/SpinBox через group)."""
from frontend_module.components.control_v2.numeric.config import NumericViewConfig
from frontend_module.components.control_v2.numeric.defaults import (
    bgr_slider_default,
    slider_default,
    spinbox_default,
)
from frontend_module.components.control_v2.numeric.facade import (
    NumericControl,
    NumericControlResult,
)
from frontend_module.components.control_v2.numeric.presenter import NumericPresenter

__all__ = [
    "NumericViewConfig",
    "NumericControl",
    "NumericControlResult",
    "NumericPresenter",
    "slider_default",
    "spinbox_default",
    "bgr_slider_default",
]
