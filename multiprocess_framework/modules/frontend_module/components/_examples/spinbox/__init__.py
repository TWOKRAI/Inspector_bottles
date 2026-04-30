# -*- coding: utf-8 -*-
"""Спинбокс: схемы + адаптер к v2."""
from multiprocess_framework.modules.frontend_module.components._examples.spinbox.adapter import (
    coerce_ui,
    create_example_spinbox,
    spinbox_binding,
    spinbox_view_config_from_ui,
)
from multiprocess_framework.modules.frontend_module.components._examples.spinbox.schemas import (
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
