# -*- coding: utf-8 -*-
"""Пайплайн: routing → rect → параметры обработок → блок → регион → камера → PipelineConfig."""

from .camera import Camera
from .migration import (
    merge_legacy_into_vision_pipeline_dict,
    migrate_crop_regions_to_pipeline_dict,
    migrate_legacy_pipeline_root,
    normalize_processor_register_payload,
)
from .pipeline_config import PipelineConfig
from .processing_block import ProcessingBlock
from .processing_params import (
    BlobDetectionParams,
    ColorDetectionParams,
    ProcessorParams,
)
from .rect import Rect
from .region import Region
from .routing import PIPELINE_PARAMS_ROUTING

__all__ = [
    "PIPELINE_PARAMS_ROUTING",
    "BlobDetectionParams",
    "Camera",
    "ColorDetectionParams",
    "PipelineConfig",
    "ProcessingBlock",
    "ProcessorParams",
    "Rect",
    "Region",
    "merge_legacy_into_vision_pipeline_dict",
    "migrate_crop_regions_to_pipeline_dict",
    "migrate_legacy_pipeline_root",
    "normalize_processor_register_payload",
]
