# -*- coding: utf-8 -*-
"""
Чекбокс v2: `CheckboxView` (Qt), `CheckboxPresenter` (регистр + права), `CheckboxControl.create` (фабрика).

CheckboxRegister (Django-style дескриптор для bool-полей) живёт в
`components/checkbox/registers.py` — pure Python без Qt-зависимостей,
плагины импортируют его через `components/registers.py` агрегат.

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
from multiprocess_framework.modules.frontend_module.components.checkbox.registers import CheckboxRegister
from multiprocess_framework.modules.frontend_module.components.checkbox.view import CheckboxView

__all__ = [
    "CheckboxView",
    "CheckboxViewConfig",
    "CheckboxPresenter",
    "CheckboxControl",
    "CheckboxControlResult",
    "CheckboxRegister",
    "checkbox_left",
    "checkbox_right",
]
