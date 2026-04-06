# -*- coding: utf-8 -*-
"""Плоский регистр процессора для GUI: цвет/площадь + legacy vision_pipeline и ROI."""

from __future__ import annotations

from typing import Annotated, Any, ClassVar, Dict, List

from pydantic import Field

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    RegisterDispatchMeta,
    SchemaBase,
    register_schema,
)

from multiprocess_prototype_v2.registers.processings.color_detection import (
    CONTROL_PROCESSOR_1_ROUTING,
    CONTROL_PROCESSOR_2_ROUTING,
)


@register_schema("ProcessorRegistersV3")
class ProcessorRegisters(SchemaBase):
    """Совмещает параметры детекции с полями вкладок ROI/постобработки."""

    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("processor",),
    )

    color_lower: Annotated[
        List[int],
        FieldMeta(
            "BGR Lower",
            info="Нижняя граница BGR.",
            routing=CONTROL_PROCESSOR_1_ROUTING,
        ),
    ] = Field(default_factory=lambda: [0, 0, 150])

    color_upper: Annotated[
        List[int],
        FieldMeta(
            "BGR Upper",
            info="Верхняя граница BGR.",
            routing=CONTROL_PROCESSOR_2_ROUTING,
        ),
    ] = Field(default_factory=lambda: [100, 100, 255])

    min_area: Annotated[
        int,
        FieldMeta(
            "Мин. площадь",
            info="Минимальная площадь контура.",
            min=10,
            max=5000,
            unit="px",
            routing=CONTROL_PROCESSOR_2_ROUTING,
        ),
    ] = 500

    max_area: Annotated[
        int,
        FieldMeta(
            "Макс. площадь",
            info="Максимальная площадь контура.",
            min=0,
            max=50000,
            unit="px",
            routing=CONTROL_PROCESSOR_2_ROUTING,
        ),
    ] = 50000

    logical_camera_ids: List[str] = Field(default_factory=list)
    vision_pipeline: Dict[str, Any] = Field(default_factory=dict)
    crop_regions: Dict[str, Any] = Field(default_factory=dict)
    post_processing_regions: Dict[str, Any] = Field(default_factory=dict)
