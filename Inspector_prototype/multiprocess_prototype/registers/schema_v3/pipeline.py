# -*- coding: utf-8 -*-
"""Каноническая схема pipeline для schema_v3."""

from __future__ import annotations

from typing import Dict, Union

from pydantic import Field

from multiprocess_framework.modules.data_schema_module import SchemaBase, register_schema

from .camera import BaseCameraRegisters, HikvisionCameraRegisters, WebcamCameraRegisters

from .processings.base_processing import BaseProcessingBlock
from .region import Region

CameraRegistersUnion = Union[WebcamCameraRegisters, HikvisionCameraRegisters, BaseCameraRegisters]


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
    """Корень схемы: словарь камер."""

    cameras: Dict[str, CameraNode] = Field(default_factory=dict)
