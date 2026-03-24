# -*- coding: utf-8 -*-
from frontend_module.components.examples.numeric.adapter import (
    coerce_ui,
    create_example_numeric,
    numeric_binding,
    numeric_view_config_from_ui,
)
from frontend_module.components.examples.numeric.schemas import (
    EXAMPLE_NUMERIC_ROUTING,
    ExampleNumericUiConfig,
    ExampleNumericValueRegister,
)

__all__ = [
    "EXAMPLE_NUMERIC_ROUTING",
    "ExampleNumericUiConfig",
    "ExampleNumericValueRegister",
    "coerce_ui",
    "create_example_numeric",
    "numeric_binding",
    "numeric_view_config_from_ui",
]
