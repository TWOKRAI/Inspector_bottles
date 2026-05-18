# -*- coding: utf-8 -*-
"""Combo: схемы + адаптер к v2."""

from multiprocess_framework.modules.frontend_module.components._examples.combo.adapter import (
    combo_binding,
    combo_view_config_from_ui,
    coerce_ui,
    create_example_combo,
)
from multiprocess_framework.modules.frontend_module.components._examples.combo.schemas import (
    EXAMPLE_COMBO_ROUTING,
    ExampleComboUiConfig,
    ExampleComboValueRegister,
)

__all__ = [
    "EXAMPLE_COMBO_ROUTING",
    "ExampleComboValueRegister",
    "ExampleComboUiConfig",
    "combo_binding",
    "combo_view_config_from_ui",
    "coerce_ui",
    "create_example_combo",
]
