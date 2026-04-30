# -*- coding: utf-8 -*-
"""
Компактное поле ввода числа рядом со слайдером.

Размеры — из common/sizes, шрифт — из common/typography.
Touch-клавиатура подключается снаружи (замена mousePressEvent).
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from multiprocess_framework.modules.frontend_module.components.common.sizes import (
    VALUE_INPUT_HEIGHT_PX,
    VALUE_INPUT_WIDTH_PX,
)
from multiprocess_framework.modules.frontend_module.components.common.typography import value_input_font
from multiprocess_framework.modules.frontend_module.core.qt_imports import QLineEdit, Qt


def create_numeric_line_edit(
    parent: Optional[Any],
    *,
    on_editing_finished: Callable[[], None],
) -> QLineEdit:
    """Создать ``QLineEdit``, подключить ``editingFinished``."""
    le = QLineEdit(parent)
    le.setFont(value_input_font())
    le.setFixedSize(VALUE_INPUT_WIDTH_PX, VALUE_INPUT_HEIGHT_PX)
    le.setAlignment(Qt.AlignmentFlag.AlignCenter)
    le.editingFinished.connect(on_editing_finished)
    return le
