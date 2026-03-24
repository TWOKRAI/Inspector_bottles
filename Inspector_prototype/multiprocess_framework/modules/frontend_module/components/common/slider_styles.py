# -*- coding: utf-8 -*-
"""
Стили горизонтального слайдера: QSS ручки, высота трека.

Используется примитивом styled_slider и SliderValueView.
"""
SLIDER_MIN_HEIGHT_PX = 45
LAYOUT_SPACING_AFTER_LABEL_PX = 5
LAYOUT_SPACING_BEFORE_SLIDER_PX = 20
LAYOUT_SPACING_AFTER_SLIDER_PX = 25
LAYOUT_SPACING_PX = 5

SLIDER_HANDLE_STYLESHEET = """
    QSlider::handle:horizontal {
        height: 50px; width: 25px; margin: -15px 0;
        border: 2px solid #4682B4; border-radius: 7px; background: gray;
    }
"""


def apply_slider_handle_style(slider: object) -> None:
    """Применить QSS ручки горизонтального слайдера."""
    slider.setStyleSheet(SLIDER_HANDLE_STYLESHEET)
