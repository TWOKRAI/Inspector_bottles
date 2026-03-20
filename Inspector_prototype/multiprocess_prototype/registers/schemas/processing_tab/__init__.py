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
from .processor import PROCESSOR_ROUTING, ProcessorRegisters
from .renderer import RENDERER_ROUTING, RendererRegisters

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
