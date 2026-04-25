# -*- coding: utf-8 -*-
"""
Slider v2: SliderValueView (value), SliderControl.create (фасад).

По аналогии с checkbox: SliderControl.create возвращает SliderControlResult(widget, presenter).
"""
from multiprocess_framework.modules.frontend_module.components.slider.config import SliderConfig
from multiprocess_framework.modules.frontend_module.components.slider.defaults import (
    bgr_slider_default,
    slider_default,
)
from multiprocess_framework.modules.frontend_module.components.slider.facade import (
    SliderControl,
    SliderControlResult,
)
from multiprocess_framework.modules.frontend_module.components.slider.presenter import SliderPresenter
from multiprocess_framework.modules.frontend_module.components.slider.view import SliderValueView

__all__ = [
    "SliderConfig",
    "SliderPresenter",
    "SliderValueView",
    "SliderControl",
    "SliderControlResult",
    "slider_default",
    "bgr_slider_default",
]
