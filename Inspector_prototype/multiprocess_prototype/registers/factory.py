# multiprocess_prototype/registers/factory.py
"""
Фабрика регистров для frontend и backend.

Единое место создания RegistersManager и connection_map.
"""
from typing import Dict, Tuple

from registers_module import RegistersManager

from .schemas import DrawRegisters, ProcessorRegisters, RendererRegisters
from .connection_map import DEFAULT_CONNECTION_MAP


def create_registers() -> Tuple[RegistersManager, Dict[str, str]]:
    """
    Создать RegistersManager и connection_map для frontend.

    Returns:
        (RegistersManager, connection_map)
    """
    registers = RegistersManager({
        "draw": DrawRegisters(),
        "processor": ProcessorRegisters(),
        "renderer": RendererRegisters(),
    })
    return registers, dict(DEFAULT_CONNECTION_MAP)
