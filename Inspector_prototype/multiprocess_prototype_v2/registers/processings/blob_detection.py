# -*- coding: utf-8 -*-
"""Параметры blob-детекции."""

from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.data_schema_module import FieldMeta, FieldRouting, register_schema

from .base_processing import ProcessingParamsBase


CONTROL_PROCESSOR_1_ROUTING = FieldRouting(channel="control_processor_1")
CONTROL_PROCESSOR_2_ROUTING = FieldRouting(channel="control_processor_2")


@register_schema("BlobDetectionParamsV3")
class BlobDetectionParams(ProcessingParamsBase):
    """Параметры blob detection."""

    type: Literal["blob_detection"] = "blob_detection"

    threshold_step: Annotated[
        int,
        FieldMeta("Шаг порога", 
        info="Шаг бинаризации.", 
        min=1, 
        max=255, 
        routing=CONTROL_PROCESSOR_1_ROUTING),
    ] = 10

    min_area: Annotated[
        int,
        FieldMeta("Мин. площадь", 
        info="Минимальная площадь blob.", 
        min=1, 
        max=100000, 
        unit="px", 
        routing=CONTROL_PROCESSOR_2_ROUTING),
    ] = 100
