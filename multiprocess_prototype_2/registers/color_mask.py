"""ColorMaskRegisters — HSV-пороги для ColorMaskPlugin.

Регистр: runtime-параметры HSV-фильтрации.
GUI получает виджеты автоматически из FieldMeta (слайдеры 0..179, 0..255).
Backend читает self._reg.min_h / max_h / ... — всегда актуальные значения.
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.data_schema_module.core.field_meta import FieldMeta
from multiprocess_framework.modules.data_schema_module.core.schema_base import SchemaBase


class ColorMaskRegisters(SchemaBase):
    """HSV-пороги для color_mask плагина.

    6 полей с FieldMeta для автогенерации GUI-виджетов.
    Hue: 0..179 (OpenCV HSV convention).
    Saturation, Value: 0..255.
    """

    min_h: Annotated[int, FieldMeta(
        "Min Hue", info="Нижняя граница H в HSV", min=0, max=179, unit="°",
    )] = 0
    max_h: Annotated[int, FieldMeta(
        "Max Hue", info="Верхняя граница H в HSV", min=0, max=179, unit="°",
    )] = 179
    min_s: Annotated[int, FieldMeta(
        "Min Saturation", info="Нижняя граница S", min=0, max=255,
    )] = 50
    max_s: Annotated[int, FieldMeta(
        "Max Saturation", info="Верхняя граница S", min=0, max=255,
    )] = 255
    min_v: Annotated[int, FieldMeta(
        "Min Value", info="Нижняя граница V", min=0, max=255,
    )] = 50
    max_v: Annotated[int, FieldMeta(
        "Max Value", info="Верхняя граница V", min=0, max=255,
    )] = 255
