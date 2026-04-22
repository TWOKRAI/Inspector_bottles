# multiprocess_prototype/registers/schemas/__init__.py
"""Схемы регистров приложения (канон для GUI и backend прототипа)."""

from .camera_tab import (
    CAMERA_REGISTER,
    CAMERA_ROUTING,
    CameraRegisters,
    camera_process_boot_values,
)
from .pipeline import (
    BlobDetectionParams,
    Camera,
    ColorDetectionParams,
    PipelineConfig,
    ProcessingBlock,
    ProcessorParams,
    Rect,
    Region,
    migrate_crop_regions_to_pipeline_dict,
)
from .processing_tab import (
    PROCESSOR_REGISTER,
    PROCESSOR_ROUTING,
    ProcessorRegisters,
    RENDERER_REGISTER,
    RENDERER_ROUTING,
    RendererRegisters,
    processor_max_area_clamp,
    processor_process_boot_values,
    renderer_process_boot_values,
)

__all__ = [
    "BlobDetectionParams",
    "Camera",
    "ColorDetectionParams",
    "PipelineConfig",
    "ProcessingBlock",
    "ProcessorParams",
    "Rect",
    "Region",
    "migrate_crop_regions_to_pipeline_dict",
    "CAMERA_REGISTER",
    "CAMERA_ROUTING",
    "CameraRegisters",
    "camera_process_boot_values",
    "PROCESSOR_REGISTER",
    "PROCESSOR_ROUTING",
    "ProcessorRegisters",
    "RENDERER_REGISTER",
    "RENDERER_ROUTING",
    "RendererRegisters",
    "processor_process_boot_values",
    "renderer_process_boot_values",
    "processor_max_area_clamp",
]
