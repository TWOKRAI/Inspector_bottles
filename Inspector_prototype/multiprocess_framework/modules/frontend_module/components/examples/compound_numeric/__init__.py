# -*- coding: utf-8 -*-
"""Составной числовой контрол (BGR): схемы + адаптер."""
from frontend_module.components.examples.compound_numeric.adapter import (
    coerce_ui,
    compound_numeric_binding,
    compound_numeric_view_config_from_ui,
    create_example_compound_numeric,
)
from frontend_module.components.examples.compound_numeric.schemas import (
    EXAMPLE_BGR_ROUTING,
    ExampleBgrTripletRegister,
    ExampleCompoundNumericUiConfig,
)

__all__ = [
    "EXAMPLE_BGR_ROUTING",
    "ExampleBgrTripletRegister",
    "ExampleCompoundNumericUiConfig",
    "coerce_ui",
    "compound_numeric_binding",
    "compound_numeric_view_config_from_ui",
    "create_example_compound_numeric",
]
