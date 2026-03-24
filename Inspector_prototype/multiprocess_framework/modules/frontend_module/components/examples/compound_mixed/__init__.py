# -*- coding: utf-8 -*-
"""Смешанный составной контрол: схемы + адаптер."""
from frontend_module.components.examples.compound_mixed.adapter import (
    coerce_ui,
    create_example_compound_mixed,
)
from frontend_module.components.examples.compound_mixed.schemas import (
    EXAMPLE_MIXED_ROUTING,
    ExampleCompoundMixedUiConfig,
    ExampleMixedBoolRegister,
    ExampleMixedFloatRegister,
)

__all__ = [
    "EXAMPLE_MIXED_ROUTING",
    "ExampleCompoundMixedUiConfig",
    "ExampleMixedBoolRegister",
    "ExampleMixedFloatRegister",
    "coerce_ui",
    "create_example_compound_mixed",
]
