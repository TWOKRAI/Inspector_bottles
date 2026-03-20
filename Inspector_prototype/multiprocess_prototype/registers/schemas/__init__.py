# multiprocess_prototype/registers/schemas/__init__.py
"""Схемы регистров приложения (канон для GUI и backend прототипа)."""

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
