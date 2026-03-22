# -*- coding: utf-8 -*-
"""Slider — value-контрол QLineEdit + QSlider."""
from frontend_module.components.controls.v2.slider.config import SliderConfig
from frontend_module.components.controls.v2.slider.defaults import (
    bgr_slider_default,
    slider_default,
)
from frontend_module.components.controls.v2.slider.view import SliderValueView

__all__ = ["SliderConfig", "SliderValueView", "slider_default", "bgr_slider_default"]
