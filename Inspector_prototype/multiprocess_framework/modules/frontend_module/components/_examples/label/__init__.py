# -*- coding: utf-8 -*-
"""Подпись (LabelView): только UI-схема."""
from multiprocess_framework.modules.frontend_module.components._examples.label.adapter import (
    LabelExampleResult,
    coerce_ui,
    create_example_label,
    label_config_from_ui,
)
from multiprocess_framework.modules.frontend_module.components._examples.label.schemas import (
    ExampleLabelUiConfig,
)

__all__ = [
    "ExampleLabelUiConfig",
    "LabelExampleResult",
    "coerce_ui",
    "create_example_label",
    "label_config_from_ui",
]
