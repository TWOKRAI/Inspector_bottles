# -*- coding: utf-8 -*-
"""Чекбокс v2 — CheckboxView, CheckboxControl."""
from frontend_module.components.controls.v2.checkbox.config import CheckboxViewConfig
from frontend_module.components.controls.v2.checkbox.defaults import (
    checkbox_left,
    checkbox_right,
)
from frontend_module.components.controls.v2.checkbox.facade import (
    CheckboxControl,
    CheckboxControlResult,
)

__all__ = [
    "CheckboxViewConfig",
    "CheckboxControl",
    "CheckboxControlResult",
    "checkbox_left",
    "checkbox_right",
]
