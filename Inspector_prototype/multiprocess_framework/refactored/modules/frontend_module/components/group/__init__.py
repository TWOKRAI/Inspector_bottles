# -*- coding: utf-8 -*-
"""Группы компонентов — объединение Label + Value и произвольные композиции."""
from frontend_module.components.group.config import (
    GroupConfig,
    LabeledNumericGroupConfig,
)
from frontend_module.components.group.defaults import (
    label_bgr_slider_default,
    label_slider_default,
    label_spinbox_default,
)
from frontend_module.components.group.labeled_numeric_factory import (
    create_labeled_numeric_view,
)
from frontend_module.components.group.view import LabeledNumericGroupView

__all__ = [
    "GroupConfig",
    "LabeledNumericGroupConfig",
    "LabeledNumericGroupView",
    "create_labeled_numeric_view",
    "label_slider_default",
    "label_spinbox_default",
    "label_bgr_slider_default",
]
