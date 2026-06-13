"""HsvMaskRegisters — HSV-пороги (live-tunable слайдеры через GUI)."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("HsvMaskRegistersV1")
class HsvMaskRegisters(SchemaBase):
    """HSV-диапазон маски. Hue 0..179 (OpenCV), Sat/Val 0..255."""

    h_min: Annotated[
        int,
        FieldMeta("Min Hue", info="Нижняя граница H (0..179). h_min>h_max → wrap (красный)", min=0, max=179, unit="°"),
    ] = 0
    h_max: Annotated[
        int,
        FieldMeta("Max Hue", info="Верхняя граница H (0..179). h_min>h_max → оборот через 0", min=0, max=179, unit="°"),
    ] = 179
    s_min: Annotated[int, FieldMeta("Min Saturation", info="Нижняя граница S", min=0, max=255)] = 80
    s_max: Annotated[int, FieldMeta("Max Saturation", info="Верхняя граница S", min=0, max=255)] = 255
    v_min: Annotated[int, FieldMeta("Min Value", info="Нижняя граница V", min=0, max=255)] = 80
    v_max: Annotated[int, FieldMeta("Max Value", info="Верхняя граница V", min=0, max=255)] = 255
