# -*- coding: utf-8 -*-
"""
Общие константы и утилиты для control_v2.

- typography: шрифты для подписей и полей ввода
- sizes: размеры виджетов
- field_sync: синхронизация значения с окружением после записи в регистр
- legacy_sync: обновление legacy ui_elements/controls для совместимости
"""
from frontend_module.components.common.field_sync import (
    publish_control_value_to_observers,
)
from frontend_module.components.common.legacy_sync import (
    publish_legacy_ui_refs,
)
from frontend_module.components.common.sizes import (
    VALUE_INPUT_HEIGHT_PX,
    VALUE_INPUT_WIDTH_PX,
)
from frontend_module.components.common.typography import (
    label_font,
    value_input_font,
)

__all__ = [
    "label_font",
    "value_input_font",
    "VALUE_INPUT_WIDTH_PX",
    "VALUE_INPUT_HEIGHT_PX",
    "publish_control_value_to_observers",
    "publish_legacy_ui_refs",
]
