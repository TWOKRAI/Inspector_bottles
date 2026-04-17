"""Register schemas and factory for Inspector Prototype v3.

Register names, create_registers() factory, and re-exports.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from registers_module import RegistersManager, build_connection_map_from_registers

from .camera import GuiCameraRegisters
from .processor import ProcessorRegisters
from .renderer import RendererRegisters

# Register name constants
CAMERA_REGISTER = "camera"
PROCESSOR_REGISTER = "processor"
RENDERER_REGISTER = "renderer"


def create_registers() -> Tuple[RegistersManager, Dict[str, str]]:
    """Create RegistersManager with all register schemas."""
    registers: Dict[str, Any] = {
        CAMERA_REGISTER: GuiCameraRegisters(),
        PROCESSOR_REGISTER: ProcessorRegisters(),
        RENDERER_REGISTER: RendererRegisters(),
    }
    connection_map = build_connection_map_from_registers(registers)
    return RegistersManager(registers=registers, connection_map=connection_map), connection_map


__all__ = [
    "CAMERA_REGISTER", "PROCESSOR_REGISTER", "RENDERER_REGISTER",
    "create_registers",
    "GuiCameraRegisters", "ProcessorRegisters", "RendererRegisters",
]
