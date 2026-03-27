# -*- coding: utf-8 -*-
"""Параметры алгоритмов (дискриминируемый Union по полю type)."""

from __future__ import annotations

from typing import Annotated, List, Literal, Union

from pydantic import Field, field_validator

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase, register_schema

from .routing import PIPELINE_PARAMS_ROUTING


@register_schema("ColorDetectionParams")
class ColorDetectionParams(SchemaBase):
    """Параметры цветовой детекции."""

    type: Literal["color_detection"] = "color_detection"
    color_lower: Annotated[
        List[int],
        FieldMeta(
            "BGR Lower",
            info="Нижняя граница BGR для маски (B, G, R).",
            routing=PIPELINE_PARAMS_ROUTING,
        ),
    ] = Field(default_factory=lambda: [0, 0, 150])
    color_upper: Annotated[
        List[int],
        FieldMeta(
            "BGR Upper",
            info="Верхняя граница BGR для маски (B, G, R).",
            routing=PIPELINE_PARAMS_ROUTING,
        ),
    ] = Field(default_factory=lambda: [100, 100, 255])
    min_area: Annotated[
        int,
        FieldMeta(
            "Мин. площадь",
            info="Минимальная площадь контура (px).",
            min=10,
            max=5000,
            unit="px",
            routing=PIPELINE_PARAMS_ROUTING,
        ),
    ] = 500
    max_area: Annotated[
        int,
        FieldMeta(
            "Макс. площадь",
            info="Максимальная площадь контура (px).",
            min=0,
            max=50000,
            unit="px",
            routing=PIPELINE_PARAMS_ROUTING,
        ),
    ] = 50000

    @field_validator("color_lower", "color_upper")
    @classmethod
    def _three_channels(cls, v: List[int]) -> List[int]:
        if len(v) != 3:
            raise ValueError("Ожидается ровно 3 компонента BGR")
        return [int(x) for x in v]


@register_schema("BlobDetectionParams")
class BlobDetectionParams(SchemaBase):
    """Пример обработки — порог и площадь."""

    type: Literal["blob_detection"] = "blob_detection"
    threshold_step: Annotated[
        int,
        FieldMeta(
            "Шаг порога",
            info="Шаг бинаризации / пороговой сетки.",
            min=1,
            max=255,
            routing=PIPELINE_PARAMS_ROUTING,
        ),
    ] = 10
    min_area: Annotated[
        int,
        FieldMeta(
            "Мин. площадь",
            info="Минимальная площадь blob (px).",
            min=1,
            max=100000,
            unit="px",
            routing=PIPELINE_PARAMS_ROUTING,
        ),
    ] = 100


ProcessorParams = Annotated[
    Union[ColorDetectionParams, BlobDetectionParams],
    Field(discriminator="type"),
]
