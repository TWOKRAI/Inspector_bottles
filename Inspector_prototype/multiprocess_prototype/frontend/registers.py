# multiprocess_prototype\frontend\registers.py
"""
Сборка RegistersManager и connection_map для GUI.
"""

from typing import Any, Dict, Tuple

from registers_module import RegistersManager
from shared_registers import DrawRegisters


def create_frontend_registers() -> Tuple[RegistersManager, Dict[str, str]]:
    """
    Создать RegistersManager и connection_map для frontend.

    Returns:
        (RegistersManager, connection_map)
    """
    registers = RegistersManager({"draw": DrawRegisters()})
    connection_map = {"draw": "renderer"}
    return registers, connection_map
