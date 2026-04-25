# -*- coding: utf-8 -*-
"""Числовые контролы v2 — фасад NumericControl (Slider/SpinBox через group)."""
from multiprocess_framework.modules.frontend_module.components.numeric.config import NumericViewConfig
from multiprocess_framework.modules.frontend_module.components.numeric.defaults import (
    bgr_slider_default,
    slider_default,
    spinbox_default,
)
from multiprocess_framework.modules.frontend_module.components.numeric.facade import (
    NumericControl,
    NumericControlResult,
)
from multiprocess_framework.modules.frontend_module.components.numeric.presenter import NumericPresenter

__all__ = [
    "NumericViewConfig",
    "NumericControl",
    "NumericControlResult",
    "NumericPresenter",
    "slider_default",
    "spinbox_default",
    "bgr_slider_default",
]
