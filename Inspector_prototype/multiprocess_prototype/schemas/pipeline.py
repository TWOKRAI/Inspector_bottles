# -*- coding: utf-8 -*-
"""Каноническая схема pipeline (пакет multiprocess_prototype.schemas)."""

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

from .camera import BaseCameraRegisters, HikvisionCameraRegisters, WebcamCameraRegisters

from .processings.base_processing import BaseProcessingBlock
from .region import Region

CameraRegistersUnion = Union[WebcamCameraRegisters, HikvisionCameraRegisters, BaseCameraRegisters]

CAMERAS_FIELD_ROUTING = FieldRouting(
    channel="control_processor",
    process_targets=("processor",),
)


@register_schema("RegionNodeV3")
class RegionNode(Region):
    """Регион в составе pipeline: поля ROI + словарь обработок."""

    processing_blocks: Dict[str, BaseProcessingBlock] = Field(default_factory=dict)


@register_schema("CameraNodeV3")
class CameraNode(SchemaBase):
    """Камера: регистры и регионы."""

    enabled: bool = True
    registers: CameraRegistersUnion = Field(default_factory=BaseCameraRegisters)
    regions: Dict[str, RegionNode] = Field(default_factory=dict)


@register_schema("PipelineV3")
class Pipeline(SchemaBase):
    """
    Корень схемы: словарь камер.

    Метаданные диспетчеризации (ранее отдельная обёртка ``PipelineRegisterRoot``)
    перенесены сюда: при использовании как регистра процессора — ``register_update``
    на канал processor по ``register_dispatch`` и ``FieldMeta`` поля ``cameras``.
    """

    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("processor",),
    )

    cameras: Annotated[
        Dict[str, CameraNode],
        FieldMeta(
            "Cameras",
            info="Камеры → регионы → обработки (multiprocess_prototype.schemas).",
            routing=CAMERAS_FIELD_ROUTING,
        ),
    ] = Field(default_factory=dict)
