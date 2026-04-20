"""Blob detection algorithm parameters."""

from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.data_schema_module import FieldMeta, register_schema

from ...constants import CONTROL_PROCESSOR_1_ROUTING, CONTROL_PROCESSOR_2_ROUTING
from .base import ProcessingParamsBase


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


__all__ = ["BlobDetectionParams"]
