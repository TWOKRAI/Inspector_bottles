# multiprocess_prototype/registers/factory.py
"""
Фабрика регистров для frontend и backend.

Состав менеджера задаётся в :mod:`multiprocess_prototype.registers.registry`
(``REGISTER_MODELS``); здесь только сборка ``RegistersManager`` и ``connection_map``.
"""
from typing import Dict, Tuple

from registers_module import RegistersManager, build_connection_map_from_registers

from .registry import default_register_instances


def build_default_connection_map() -> Dict[str, str]:
    """Карта доставки ``register_update`` из метаданных полей и ``register_dispatch``."""
    reg_dict = default_register_instances()
    return build_connection_map_from_registers(reg_dict)


def create_registers() -> Tuple[RegistersManager, Dict[str, str]]:
    """
    Создать RegistersManager и connection_map для frontend.

    Returns:
        (RegistersManager, connection_map)
    """
    reg_dict = default_register_instances()
    registers = RegistersManager(reg_dict)
    return registers, build_connection_map_from_registers(reg_dict)
