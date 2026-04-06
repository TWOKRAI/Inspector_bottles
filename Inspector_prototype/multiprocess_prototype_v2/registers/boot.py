# -*- coding: utf-8 -*-
"""Boot-значения процессов из канонических схем registers/."""

from __future__ import annotations

from typing import Any, Dict

from multiprocess_prototype_v2.registers.gui_camera_registers import GuiCameraRegisters
from multiprocess_prototype_v2.registers.processings import ColorDetectionParams
from multiprocess_prototype_v2.registers.renderer import RendererRegisters


def camera_process_boot_values() -> Dict[str, Any]:
    return GuiCameraRegisters().model_dump()


def renderer_process_boot_values() -> Dict[str, Any]:
    return RendererRegisters().model_dump()


def processor_process_boot_values() -> Dict[str, Any]:
    """Совместимость: плоские поля как у ProcessorRegisters + пустые коллекции."""
    from multiprocess_prototype_v2.registers.processor_registers import ProcessorRegisters

    return ProcessorRegisters().model_dump()


def processor_max_area_clamp() -> int:
    meta = ColorDetectionParams.get_field_meta("max_area")
    if meta is None or meta.max is None:
        return 50000
    return int(meta.max)
