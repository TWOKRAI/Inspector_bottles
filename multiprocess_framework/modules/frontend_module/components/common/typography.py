# -*- coding: utf-8 -*-
"""
Шрифты для подписей и полей ввода в контролах.

Числовые константы размеров — в sizes.py.
"""
from __future__ import annotations

from multiprocess_framework.modules.frontend_module.core.qt_imports import QFont


LABEL_FONT_FAMILY = "Arial"
LABEL_FONT_SIZE = 11
VALUE_INPUT_FONT_FAMILY = "Arial"
VALUE_INPUT_FONT_SIZE = 12


def label_font() -> QFont:
    """Шрифт для подписей контролов."""
    return QFont(LABEL_FONT_FAMILY, LABEL_FONT_SIZE)


def value_input_font() -> QFont:
    """Шрифт для полей ввода чисел."""
    return QFont(VALUE_INPUT_FONT_FAMILY, VALUE_INPUT_FONT_SIZE)
