# -*- coding: utf-8 -*-
"""Группы компонентов — объединение Label + Value и произвольные композиции."""
from frontend_module.components.controls.v2.group.config import (
    GroupConfig,
    LabeledNumericGroupConfig,
)
from frontend_module.components.controls.v2.group.defaults import (
    label_bgr_slider_default,
    label_slider_default,
    label_spinbox_default,
)
from frontend_module.components.controls.v2.group.view import (
    LabeledNumericGroupView,
    create_labeled_numeric_view,
)

__all__ = [
    "GroupConfig",
    "LabeledNumericGroupConfig",
    "LabeledNumericGroupView",
    "create_labeled_numeric_view",
    "label_slider_default",
    "label_spinbox_default",
    "label_bgr_slider_default",
]
