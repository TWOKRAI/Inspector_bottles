"""Boot values for processes, generated from canonical register schemas."""

from __future__ import annotations

from typing import Any, Dict

from .camera import GuiCameraRegisters
from .processor import ColorDetectionParams, ProcessorRegisters
from .renderer import RendererRegisters


def camera_process_boot_values() -> Dict[str, Any]:
    return GuiCameraRegisters().model_dump()


def renderer_process_boot_values() -> Dict[str, Any]:
    return RendererRegisters().model_dump()


def processor_process_boot_values() -> Dict[str, Any]:
    """Flat fields as in ProcessorRegisters + empty collections."""
    return ProcessorRegisters().model_dump()


def processor_max_area_clamp() -> int:
    meta = ColorDetectionParams.get_field_meta("max_area")
    if meta is None or meta.max is None:
        return 50000
    return int(meta.max)
