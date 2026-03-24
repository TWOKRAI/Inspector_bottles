# -*- coding: utf-8 -*-
"""
Стили горизонтального слайдера: реэкспорт из `styles` + отступ для layout.

Используется SliderValueView и styled_slider.
"""
from __future__ import annotations

from frontend_module.components.common.styles import (
    SLIDER_MIN_HEIGHT_PX,
    apply_slider_handle_style,
)

LAYOUT_SPACING_AFTER_LABEL_PX = 5
LAYOUT_SPACING_BEFORE_SLIDER_PX = 20
LAYOUT_SPACING_AFTER_SLIDER_PX = 25
LAYOUT_SPACING_PX = 5

__all__ = [
    "LAYOUT_SPACING_PX",
    "LAYOUT_SPACING_AFTER_LABEL_PX",
    "LAYOUT_SPACING_BEFORE_SLIDER_PX",
    "LAYOUT_SPACING_AFTER_SLIDER_PX",
    "SLIDER_MIN_HEIGHT_PX",
    "apply_slider_handle_style",
]
