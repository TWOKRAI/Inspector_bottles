# -*- coding: utf-8 -*-
"""
Примитивы UI для пакета ``controls``.

Реиспользуемые фабрики без зависимости от регистра; стили — из ``common/typography``,
размеры — из ``common/sizes``. Для семантики debounce слайдера см. ``value_bridge``.
"""

from frontend_module.components.controls.primitives.control_label import create_control_label
from frontend_module.components.controls.primitives.numeric_line_edit import create_numeric_line_edit
from frontend_module.components.controls.primitives.styled_slider import (
    create_styled_horizontal_slider,
)
from frontend_module.components.controls.primitives.value_bridge import (
    SLIDER_COMMIT_DELAY_MS,
    schedule_slider_value_commit,
)

__all__ = [
    "create_control_label",
    "create_numeric_line_edit",
    "create_styled_horizontal_slider",
    "SLIDER_COMMIT_DELAY_MS",
    "schedule_slider_value_commit",
]
