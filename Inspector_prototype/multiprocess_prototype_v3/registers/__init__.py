"""Register schemas and factory for Inspector Prototype v3.

Structure:
  registers/constants.py  — register names, routing channels, shared defaults
  registers/camera/       — camera schemas, type policy, Hikvision helpers
  registers/processor/    — processor register, detection algorithm params
  registers/renderer/     — renderer display parameters
  registers/pipeline/     — vision pipeline hierarchy + widget bridge
  registers/commands/     — GUI command routing and payload catalog
  registers/payloads/     — GUI payload helpers (crop/post-processing)
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from registers_module import RegistersManager, build_connection_map_from_registers

from .camera import GuiCameraRegisters
from .commands import GUI_COMMAND_CATALOG
from .constants import CAMERA_REGISTER, PROCESSOR_REGISTER, RENDERER_REGISTER
from .processor import ProcessorRegisters
from .renderer import RendererRegisters


def create_registers() -> Tuple[RegistersManager, Dict[str, str]]:
    """Create RegistersManager with all GUI register schemas."""
    registers: Dict[str, Any] = {
        CAMERA_REGISTER: GuiCameraRegisters(),
        PROCESSOR_REGISTER: ProcessorRegisters(),
        RENDERER_REGISTER: RendererRegisters(),
    }
    connection_map = build_connection_map_from_registers(registers)
    return RegistersManager(registers=registers, connection_map=connection_map), connection_map


__all__ = [
    "CAMERA_REGISTER", "PROCESSOR_REGISTER", "RENDERER_REGISTER",
    "GUI_COMMAND_CATALOG",
    "create_registers",
    "GuiCameraRegisters", "ProcessorRegisters", "RendererRegisters",
]
