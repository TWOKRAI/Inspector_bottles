"""Processor register schema — flat GUI register for detection parameters."""

from __future__ import annotations

from typing import Annotated, Any, ClassVar, Dict, List

from pydantic import Field

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    RegisterDispatchMeta,
    SchemaBase,
    register_schema,
)

from ..constants import (
    CONTROL_PROCESSOR_1_ROUTING,
    CONTROL_PROCESSOR_2_ROUTING,
    DEFAULT_COLOR_LOWER,
    DEFAULT_COLOR_UPPER,
    DEFAULT_MAX_AREA,
    DEFAULT_MIN_AREA,
    PIPELINE_PARAMS_ROUTING,
)


@register_schema("ProcessorRegistersV3")
class ProcessorRegisters(SchemaBase):
    """Processor parameters: color range, area thresholds, ROI/pipeline."""

    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("processor",),
    )

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

    logical_camera_ids: List[str] = Field(default_factory=list)

    vision_pipeline: Annotated[
        Dict[str, Any],
        FieldMeta("Vision Pipeline", info="Per-camera region tree (Pipeline schema).", routing=PIPELINE_PARAMS_ROUTING),
    ] = Field(default_factory=dict)

    crop_regions: Dict[str, Any] = Field(default_factory=dict)
    post_processing_regions: Dict[str, Any] = Field(default_factory=dict)


__all__ = ["ProcessorRegisters"]
