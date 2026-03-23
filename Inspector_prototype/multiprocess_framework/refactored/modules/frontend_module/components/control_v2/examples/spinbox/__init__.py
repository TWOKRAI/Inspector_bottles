# -*- coding: utf-8 -*-
"""Спинбокс: схемы + адаптер к v2."""
from frontend_module.components.control_v2.examples.spinbox.adapter import (
    coerce_ui,
    create_example_spinbox,
    spinbox_binding,
    spinbox_view_config_from_ui,
)
from frontend_module.components.control_v2.examples.spinbox.schemas import (
    EXAMPLE_SPINBOX_ROUTING,
    ExampleSpinboxUiConfig,
    ExampleSpinboxValueRegister,
)

__all__ = [
    "EXAMPLE_SPINBOX_ROUTING",
    "ExampleSpinboxUiConfig",
    "ExampleSpinboxValueRegister",
    "coerce_ui",
    "create_example_spinbox",
    "spinbox_binding",
    "spinbox_view_config_from_ui",
]
