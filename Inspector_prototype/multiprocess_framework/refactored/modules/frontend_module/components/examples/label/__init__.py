# -*- coding: utf-8 -*-
"""Подпись (LabelView): только UI-схема."""
from frontend_module.components.examples.label.adapter import (
    LabelExampleResult,
    coerce_ui,
    create_example_label,
    label_config_from_ui,
)
from frontend_module.components.examples.label.schemas import (
    ExampleLabelUiConfig,
)

__all__ = [
    "ExampleLabelUiConfig",
    "LabelExampleResult",
    "coerce_ui",
    "create_example_label",
    "label_config_from_ui",
]
