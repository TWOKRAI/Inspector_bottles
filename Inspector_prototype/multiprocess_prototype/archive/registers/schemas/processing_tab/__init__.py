# -*- coding: utf-8 -*-
"""
Синхронизируемые регистры фичи «Обработка» (processor + renderer).

Точка импорта: ProcessorRegisters, RendererRegisters, маршрутизация, имена регистров.
"""
from .boot import (
    processor_max_area_clamp,
    processor_process_boot_values,
    renderer_process_boot_values,
)
from .names import PROCESSOR_REGISTER, RENDERER_REGISTER
from .nested_payload import (
    DEFAULT_CROP_CAMERA_ID,
    PostProcessingRegionEntry,
    merge_crop_regions_payload,
    merge_post_processing_payload,
    normalize_crop_regions_payload,
    normalize_post_processing_payload,
    normalize_region_entry,
)
from .processor import DEFAULT_CROP_CAMERA_FOR_REGISTER, PROCESSOR_ROUTING, ProcessorRegisters
from .renderer import RENDERER_ROUTING, RendererRegisters

__all__ = [
    "DEFAULT_CROP_CAMERA_FOR_REGISTER",
    "DEFAULT_CROP_CAMERA_ID",
    "PROCESSOR_REGISTER",
    "PROCESSOR_ROUTING",
    "PostProcessingRegionEntry",
    "ProcessorRegisters",
    "RENDERER_REGISTER",
    "RENDERER_ROUTING",
    "RendererRegisters",
    "merge_crop_regions_payload",
    "merge_post_processing_payload",
    "normalize_crop_regions_payload",
    "normalize_post_processing_payload",
    "normalize_region_entry",
    "processor_process_boot_values",
    "renderer_process_boot_values",
    "processor_max_area_clamp",
]
