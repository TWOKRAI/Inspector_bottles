"""Color detection algorithm parameters."""

from __future__ import annotations

from typing import Annotated, List, Literal

from pydantic import Field, field_validator

from multiprocess_framework.modules.data_schema_module import FieldMeta, register_schema

from ...constants import (
    CONTROL_PROCESSOR_1_ROUTING,
    CONTROL_PROCESSOR_2_ROUTING,
    DEFAULT_COLOR_LOWER,
    DEFAULT_COLOR_UPPER,
    DEFAULT_MAX_AREA,
    DEFAULT_MIN_AREA,
)
from .base import ProcessingParamsBase


@register_schema("ColorDetectionParamsV3")
class ColorDetectionParams(ProcessingParamsBase):
    """Color detection parameters (BGR range + area thresholds)."""

    type: Literal["color_detection"] = "color_detection"

    color_lower: Annotated[
        List[int],
        FieldMeta("BGR Lower", info="Нижняя граница BGR.", routing=CONTROL_PROCESSOR_1_ROUTING),
    ] = Field(default_factory=lambda: list(DEFAULT_COLOR_LOWER))

    color_upper: Annotated[
        List[int],
        FieldMeta("BGR Upper", info="Верхняя граница BGR.", routing=CONTROL_PROCESSOR_2_ROUTING),
    ] = Field(default_factory=lambda: list(DEFAULT_COLOR_UPPER))

    min_area: Annotated[
        int,
        FieldMeta("Мин. площадь", info="Минимальная площадь контура.", min=10, max=5000, unit="px", routing=CONTROL_PROCESSOR_2_ROUTING),
    ] = DEFAULT_MIN_AREA

    max_area: Annotated[
        int,
        FieldMeta("Макс. площадь", info="Максимальная площадь контура.", min=0, max=50000, unit="px", routing=CONTROL_PROCESSOR_2_ROUTING),
    ] = DEFAULT_MAX_AREA

    @field_validator("color_lower", "color_upper")
    @classmethod
    def _three_channels(cls, v: List[int]) -> List[int]:
        if len(v) != 3:
            raise ValueError("Ожидается ровно 3 компонента BGR")
        return [int(x) for x in v]


__all__ = ["ColorDetectionParams"]
