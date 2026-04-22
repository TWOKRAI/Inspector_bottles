# -*- coding: utf-8 -*-
"""
Примитивы UI для control_v2.

Переиспользуемые фабрики без зависимости от регистра.
Стили — из common/typography, common/sizes, common/slider_styles.
"""
from frontend_module.components.primitives.control_label import (
    create_control_label,
)
from frontend_module.components.primitives.numeric_line_edit import (
    create_numeric_line_edit,
)
from frontend_module.components.primitives.styled_slider import (
    create_styled_horizontal_slider,
)
from frontend_module.components.primitives.value_bridge import (
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
