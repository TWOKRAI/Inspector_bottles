"""Processing parameter schemas — color detection, blob detection."""

from __future__ import annotations

from typing import Annotated, List, Literal

from pydantic import Field, field_validator

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    FieldRouting,
    SchemaBase,
    register_schema,
)

CONTROL_PROCESSOR_1_ROUTING = FieldRouting(channel="control_processor_1")
CONTROL_PROCESSOR_2_ROUTING = FieldRouting(channel="control_processor_2")
PIPELINE_PARAMS_ROUTING = FieldRouting(channel="control_processor")


class ProcessingParamsBase(SchemaBase):
    """Base for processing algorithm parameters."""


@register_schema("ColorDetectionParamsV3")
class ColorDetectionParams(ProcessingParamsBase):
    """Color detection parameters."""

    type: Literal["color_detection"] = "color_detection"

    color_lower: Annotated[
        List[int],
        FieldMeta("BGR Lower", info="Нижняя граница BGR.", routing=CONTROL_PROCESSOR_1_ROUTING),
    ] = Field(default_factory=lambda: [0, 0, 150])

    color_upper: Annotated[
        List[int],
        FieldMeta("BGR Upper", info="Верхняя граница BGR.", routing=CONTROL_PROCESSOR_2_ROUTING),
    ] = Field(default_factory=lambda: [100, 100, 255])

    min_area: Annotated[
        int,
        FieldMeta("Мин. площадь", info="Минимальная площадь контура.", min=10, max=5000, unit="px", routing=CONTROL_PROCESSOR_2_ROUTING),
    ] = 500

    max_area: Annotated[
        int,
        FieldMeta("Макс. площадь", info="Максимальная площадь контура.", min=0, max=50000, unit="px", routing=CONTROL_PROCESSOR_2_ROUTING),
    ] = 50000

    @field_validator("color_lower", "color_upper")
    @classmethod
    def _three_channels(cls, v: List[int]) -> List[int]:
        if len(v) != 3:
            raise ValueError("Ожидается ровно 3 компонента BGR")
        return [int(x) for x in v]


@register_schema("BlobDetectionParamsV3")
class BlobDetectionParams(ProcessingParamsBase):
    """Blob detection parameters."""

    type: Literal["blob_detection"] = "blob_detection"

    threshold_step: Annotated[
        int,
        FieldMeta("Шаг порога", info="Шаг бинаризации.", min=1, max=255, routing=CONTROL_PROCESSOR_1_ROUTING),
    ] = 10

    min_area: Annotated[
        int,
        FieldMeta("Мин. площадь", info="Минимальная площадь blob.", min=1, max=100000, unit="px", routing=CONTROL_PROCESSOR_2_ROUTING),
    ] = 100
