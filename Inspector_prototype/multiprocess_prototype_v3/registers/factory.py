# -*- coding: utf-8 -*-
"""RegistersManager + connection_map для GUI прототипа v2."""

from __future__ import annotations

from typing import Any, Dict, Tuple

from registers_module import RegistersManager, build_connection_map_from_registers

from multiprocess_prototype_v3.registers.gui_camera_registers import GuiCameraRegisters
from multiprocess_prototype_v3.registers.names import CAMERA_REGISTER, PROCESSOR_REGISTER, RENDERER_REGISTER
from multiprocess_prototype_v3.registers.processor_registers import ProcessorRegisters
from multiprocess_prototype_v3.registers.renderer import RendererRegisters


def create_registers() -> Tuple[RegistersManager, Dict[str, str]]:
    registers: Dict[str, Any] = {
        CAMERA_REGISTER: GuiCameraRegisters(),
        PROCESSOR_REGISTER: ProcessorRegisters(),
        RENDERER_REGISTER: RendererRegisters(),
    }
    connection_map = build_connection_map_from_registers(registers)
    return RegistersManager(registers=registers, connection_map=connection_map), connection_map
