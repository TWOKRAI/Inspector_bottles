# -*- coding: utf-8 -*-
"""SpinBox — value-контрол QDoubleSpinBox."""
from frontend_module.components.spinbox.config import SpinBoxConfig
from frontend_module.components.spinbox.defaults import spinbox_default
from frontend_module.components.spinbox.facade import (
    SpinBoxControl,
    SpinBoxControlResult,
)
from frontend_module.components.spinbox.presenter import SpinBoxPresenter
from frontend_module.components.spinbox.view import SpinBoxValueView

__all__ = [
    "SpinBoxConfig",
    "SpinBoxControl",
    "SpinBoxControlResult",
    "SpinBoxPresenter",
    "SpinBoxValueView",
    "spinbox_default",
]
