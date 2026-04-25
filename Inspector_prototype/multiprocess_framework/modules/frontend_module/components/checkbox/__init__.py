# -*- coding: utf-8 -*-
"""
Чекбокс v2: `CheckboxView` (Qt), `CheckboxPresenter` (регистр + права), `CheckboxControl.create` (фабрика).

Документация и схемы: `checkbox/README.md`.
"""
from multiprocess_framework.modules.frontend_module.components.checkbox.config import CheckboxViewConfig
from multiprocess_framework.modules.frontend_module.components.checkbox.defaults import (
    checkbox_left,
    checkbox_right,
)
from multiprocess_framework.modules.frontend_module.components.checkbox.facade import (
    CheckboxControl,
    CheckboxControlResult,
)
from multiprocess_framework.modules.frontend_module.components.checkbox.presenter import CheckboxPresenter
from multiprocess_framework.modules.frontend_module.components.checkbox.view import CheckboxView

__all__ = [
    "CheckboxView",
    "CheckboxViewConfig",
    "CheckboxPresenter",
    "CheckboxControl",
    "CheckboxControlResult",
    "checkbox_left",
    "checkbox_right",
]
