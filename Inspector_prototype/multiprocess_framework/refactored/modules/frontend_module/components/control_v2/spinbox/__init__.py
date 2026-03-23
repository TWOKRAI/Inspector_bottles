# -*- coding: utf-8 -*-
"""SpinBox — value-контрол QDoubleSpinBox."""
from frontend_module.components.control_v2.spinbox.config import SpinBoxConfig
from frontend_module.components.control_v2.spinbox.defaults import spinbox_default
from frontend_module.components.control_v2.spinbox.facade import (
    SpinBoxControl,
    SpinBoxControlResult,
)
from frontend_module.components.control_v2.spinbox.presenter import SpinBoxPresenter
from frontend_module.components.control_v2.spinbox.view import SpinBoxValueView

__all__ = [
    "SpinBoxConfig",
    "SpinBoxControl",
    "SpinBoxControlResult",
    "SpinBoxPresenter",
    "SpinBoxValueView",
    "spinbox_default",
]
