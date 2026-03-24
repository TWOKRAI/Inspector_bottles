# -*- coding: utf-8 -*-
"""Slider: схемы + адаптер к v2."""
from frontend_module.components.examples.slider.adapter import (
    coerce_ui,
    create_example_slider,
    slider_binding,
    slider_view_config_from_ui,
)
from frontend_module.components.examples.slider.schemas import (
    EXAMPLE_SLIDER_ROUTING,
    ExampleSliderUiConfig,
    ExampleSliderValueRegister,
)

__all__ = [
    "EXAMPLE_SLIDER_ROUTING",
    "ExampleSliderValueRegister",
    "ExampleSliderUiConfig",
    "slider_binding",
    "slider_view_config_from_ui",
    "coerce_ui",
    "create_example_slider",
]
