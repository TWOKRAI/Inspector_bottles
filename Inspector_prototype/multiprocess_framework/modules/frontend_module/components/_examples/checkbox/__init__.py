# -*- coding: utf-8 -*-
"""Checkbox: схемы + адаптер к v2."""
from frontend_module.components._examples.checkbox.adapter import (
    checkbox_binding,
    checkbox_view_config_from_ui,
    coerce_ui,
    create_example_checkbox,
)
from frontend_module.components._examples.checkbox.schemas import (
    EXAMPLE_CHECKBOX_ROUTING,
    ExampleCheckboxUiConfig,
    ExampleCheckboxValueRegister,
)

__all__ = [
    "EXAMPLE_CHECKBOX_ROUTING",
    "ExampleCheckboxUiConfig",
    "ExampleCheckboxValueRegister",
    "checkbox_binding",
    "checkbox_view_config_from_ui",
    "coerce_ui",
    "create_example_checkbox",
]
