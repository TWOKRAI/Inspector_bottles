# -*- coding: utf-8 -*-
"""
Стили для слайдеров и layout-отступы.

Константы переиспользуются в primitives и slider/spinbox view.
"""
from __future__ import annotations

from typing import Any, Optional

SLIDER_MIN_HEIGHT_PX = 45
LAYOUT_SPACING_AFTER_LABEL_PX = 5
LAYOUT_SPACING_BEFORE_SLIDER_PX = 20
LAYOUT_SPACING_AFTER_SLIDER_PX = 25

SLIDER_HANDLE_STYLESHEET = """
    QSlider::handle:horizontal {
        height: 50px; width: 25px; margin: -15px 0;
        border: 2px solid #4682B4; border-radius: 7px; background: gray;
    }
"""


def apply_slider_handle_style(
    slider: object, style_session: Optional[Any] = None
) -> None:
    """
    Применить QSS ручки горизонтального слайдера.

    Если передан `style_session` с реестром `app_slider_handle` (см. прототип
    `legacy_app_style`), стиль берётся оттуда; иначе — встроенная константа.
    """
    if style_session is not None and hasattr(style_session, "register"):
        style_session.register(slider, style_id="app_slider_handle", apply_now=True)
        return
    slider.setStyleSheet(SLIDER_HANDLE_STYLESHEET)
