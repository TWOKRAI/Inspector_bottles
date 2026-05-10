"""ColorMaskRegisters — все параметры color_mask плагина.

V3_MY_PURE: register = единый источник runtime-параметров + FieldMeta.
Plugin всегда работает через self._reg (managed или локальный).
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import register_schema
from multiprocess_framework.modules.process_module.plugins import FieldMeta
from multiprocess_framework.modules.process_module.plugins import SchemaBase


@register_schema("ColorMaskRegistersV3")
class ColorMaskRegisters(SchemaBase):
    """Все параметры color_mask — runtime-tunable через GUI.

    Hue: 0..179 (OpenCV HSV convention).
    Saturation, Value: 0..255.
    """

    # HSV-пороги (runtime-tunable — GUI слайдеры)
    h_min: Annotated[int, FieldMeta(
        "Min Hue", info="Нижняя граница H в HSV (0..179 OpenCV)",
        min=0, max=179, unit="°",
    )] = 0
    h_max: Annotated[int, FieldMeta(
        "Max Hue", info="Верхняя граница H в HSV (0..179 OpenCV)",
        min=0, max=179, unit="°",
    )] = 179
    s_min: Annotated[int, FieldMeta(
        "Min Saturation", info="Нижняя граница S", min=0, max=255,
    )] = 50
    s_max: Annotated[int, FieldMeta(
        "Max Saturation", info="Верхняя граница S", min=0, max=255,
    )] = 255
    v_min: Annotated[int, FieldMeta(
        "Min Value", info="Нижняя граница V", min=0, max=255,
    )] = 50
    v_max: Annotated[int, FieldMeta(
        "Max Value", info="Верхняя граница V", min=0, max=255,
    )] = 255
