# multiprocess_prototype/registers/factory.py
"""
Фабрика регистров для frontend и backend.

Единое место создания RegistersManager и connection_map.
"""
from typing import Dict, Tuple

from registers_module import RegistersManager, build_connection_map_from_registers

from .schemas.processing_tab import (
    PROCESSOR_REGISTER,
    RENDERER_REGISTER,
    ProcessorRegisters,
    RendererRegisters,
)


def _default_register_instances() -> Dict[str, object]:
    return {
        PROCESSOR_REGISTER: ProcessorRegisters(),
        RENDERER_REGISTER: RendererRegisters(),
    }


def build_default_connection_map() -> Dict[str, str]:
    """Карта доставки register_update из метаданных (`multiprocess_prototype.registers.schemas.processing_tab`)."""
    return build_connection_map_from_registers(_default_register_instances())


def create_registers() -> Tuple[RegistersManager, Dict[str, str]]:
    """
    Создать RegistersManager и connection_map для frontend.

    Returns:
        (RegistersManager, connection_map)
    """
    reg_dict = _default_register_instances()
    registers = RegistersManager(reg_dict)
    return registers, build_connection_map_from_registers(reg_dict)
