# -*- coding: utf-8 -*-
"""Параметры цветовой детекции."""

from __future__ import annotations

from typing import Annotated, List, Literal

from pydantic import Field, field_validator

from multiprocess_framework.modules.data_schema_module import FieldMeta, FieldRouting, register_schema

from .base_processing import ProcessingParamsBase



CONTROL_PROCESSOR_1_ROUTING = FieldRouting(channel="control_processor_1")
CONTROL_PROCESSOR_2_ROUTING = FieldRouting(channel="control_processor_2")


@register_schema("ColorDetectionParamsV3")
class ColorDetectionParams(ProcessingParamsBase):
    """Параметры color detection."""

    type: Literal["color_detection"] = "color_detection"

    color_lower: Annotated[
        List[int],
        FieldMeta("BGR Lower", 
        info="Нижняя граница BGR.", 
        routing=CONTROL_PROCESSOR_1_ROUTING),
    ] = Field(default_factory=lambda: [0, 0, 150])

    color_upper: Annotated[
        List[int],
        FieldMeta("BGR Upper", 
        info="Верхняя граница BGR.", 
        routing=CONTROL_PROCESSOR_2_ROUTING ),
    ] = Field(default_factory=lambda: [100, 100, 255])

    min_area: Annotated[
        int,
        FieldMeta("Мин. площадь", 
        info="Минимальная площадь контура.", 
        min=10, 
        max=5000, 
        unit="px", 
        routing=CONTROL_PROCESSOR_2_ROUTING ),
    ] = 500

    max_area: Annotated[
        int,
        FieldMeta("Макс. площадь", 
        info="Максимальная площадь контура.", 
        min=0, 
        max=50000, 
        unit="px", 
        routing=CONTROL_PROCESSOR_2_ROUTING ),
    ] = 50000

    @field_validator("color_lower", "color_upper")
    @classmethod
    def _three_channels(cls, v: List[int]) -> List[int]:
        if len(v) != 3:
            raise ValueError("Ожидается ровно 3 компонента BGR")
        return [int(x) for x in v]
