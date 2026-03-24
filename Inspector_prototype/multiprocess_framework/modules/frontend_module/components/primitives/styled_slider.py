# -*- coding: utf-8 -*-
"""
Горизонтальный ``QSlider`` в стиле control: QSS ручки, без реакции на колёсико.

Диапазон и значение задаёт потребитель (виджет с метаданными регистра).
"""
from __future__ import annotations

from typing import Any, Optional

from frontend_module.components.common.slider_styles import (
    SLIDER_MIN_HEIGHT_PX,
    apply_slider_handle_style,
)
from frontend_module.core.qt_imports import QSlider, Qt


def create_styled_horizontal_slider(parent: Optional[Any]) -> QSlider:
    """Новый горизонтальный слайдер с применённым QSS и wheelEvent-заглушкой."""
    slider = QSlider(Qt.Horizontal, parent)
    slider.setMinimumHeight(SLIDER_MIN_HEIGHT_PX)
    slider.wheelEvent = lambda e: None  # type: ignore[assignment]
    apply_slider_handle_style(slider)
    return slider
