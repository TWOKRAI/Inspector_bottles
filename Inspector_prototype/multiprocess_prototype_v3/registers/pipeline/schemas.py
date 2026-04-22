"""Vision pipeline hierarchical schema: Pipeline → CameraNode → RegionNode → blocks."""

from __future__ import annotations

from typing import Annotated, ClassVar, Dict, Union

from pydantic import Field

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    FieldRouting,
    RegisterDispatchMeta,
    SchemaBase,
    register_schema,
)

from ..camera.schemas import BaseCameraRegisters, HikvisionCameraRegisters, WebcamCameraRegisters
from ..processor.processings.base import BaseProcessingBlock
from .processing_node import ProcessingNode
from .region import Region

CameraRegistersUnion = Union[WebcamCameraRegisters, HikvisionCameraRegisters, BaseCameraRegisters]

CAMERAS_FIELD_ROUTING = FieldRouting(
    channel="control_processor",
    process_targets=("processor",),
)


@register_schema("RegionNodeV3")
class RegionNode(Region):
    """Region in pipeline: ROI fields + dict of processing blocks (legacy) + nodes (Phase 5a)."""

    # Устаревшее поле — оставлено для обратной совместимости
    processing_blocks: Dict[str, BaseProcessingBlock] = Field(default_factory=dict)

    # Новый граф узлов обработки (Phase 5a — линейная цепочка, Phase 8 — полный граф)
    nodes: Dict[str, ProcessingNode] = Field(default_factory=dict)


@register_schema("CameraNodeV3")
class CameraNode(SchemaBase):
    """Camera in pipeline: registers and regions."""

    enabled: bool = True
    registers: CameraRegistersUnion = Field(default_factory=BaseCameraRegisters)
    regions: Dict[str, RegionNode] = Field(default_factory=dict)


@register_schema("PipelineV3")
class Pipeline(SchemaBase):
    """Root pipeline schema: dict of cameras."""

    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("processor",),
    )

    cameras: Annotated[
        Dict[str, CameraNode],
        FieldMeta("Cameras", info="Cameras → regions → processing blocks.", routing=CAMERAS_FIELD_ROUTING),
    ] = Field(default_factory=dict)


__all__ = ["CameraRegistersUnion", "RegionNode", "CameraNode", "Pipeline"]
