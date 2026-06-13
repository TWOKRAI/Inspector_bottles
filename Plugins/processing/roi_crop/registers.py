"""RoiCropRegisters — один прямоугольный ROI скалярными полями (live-tunable)."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("RoiCropRegistersV1")
class RoiCropRegisters(SchemaBase):
    """Прямоугольная область интереса в пикселях. Все поля — live (слайдеры/числа)."""

    x: Annotated[
        int,
        FieldMeta("ROI X", info="Левый край области (px)", min=0, max=8000, unit="px"),
    ] = 0
    y: Annotated[
        int,
        FieldMeta("ROI Y", info="Верхний край области (px)", min=0, max=8000, unit="px"),
    ] = 0
    width: Annotated[
        int,
        FieldMeta("ROI Width", info="Ширина области (px); 0 = до правого края кадра", min=0, max=8000, unit="px"),
    ] = 0
    height: Annotated[
        int,
        FieldMeta("ROI Height", info="Высота области (px); 0 = до нижнего края кадра", min=0, max=8000, unit="px"),
    ] = 0
