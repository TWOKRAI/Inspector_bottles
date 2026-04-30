# -*- coding: utf-8 -*-
"""SpinBox — value-контрол QDoubleSpinBox."""
from multiprocess_framework.modules.frontend_module.components.spinbox.config import SpinBoxConfig
from multiprocess_framework.modules.frontend_module.components.spinbox.defaults import spinbox_default
from multiprocess_framework.modules.frontend_module.components.spinbox.facade import (
    SpinBoxControl,
    SpinBoxControlResult,
)
from multiprocess_framework.modules.frontend_module.components.spinbox.presenter import SpinBoxPresenter
from multiprocess_framework.modules.frontend_module.components.spinbox.view import SpinBoxValueView

__all__ = [
    "SpinBoxConfig",
    "SpinBoxControl",
    "SpinBoxControlResult",
    "SpinBoxPresenter",
    "SpinBoxValueView",
    "spinbox_default",
]
