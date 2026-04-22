# -*- coding: utf-8 -*-
"""
Типы и реэкспорт канонических нормализаторов вложенных полей ProcessorRegisters.

См. crop_regions_payload.py, post_processing_payload.py, ADR-091/092.
"""
from __future__ import annotations

from .crop_regions_payload import (
    merge_crop_regions_payload,
    normalize_crop_regions_payload,
)
from .post_processing_payload import (
    PostProcessingRegionEntry,
    merge_post_processing_payload,
    normalize_post_processing_payload,
    normalize_region_entry,
)

DEFAULT_CROP_CAMERA_ID = "default"

__all__ = [
    "DEFAULT_CROP_CAMERA_ID",
    "PostProcessingRegionEntry",
    "merge_crop_regions_payload",
    "merge_post_processing_payload",
    "normalize_crop_regions_payload",
    "normalize_post_processing_payload",
    "normalize_region_entry",
]
