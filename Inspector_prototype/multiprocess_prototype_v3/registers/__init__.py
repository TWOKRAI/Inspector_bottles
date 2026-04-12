# multiprocess_prototype_v3/registers/__init__.py
"""Схемы регистров и фабрика RegistersManager."""

from .factory import create_registers, load_register_snapshot, save_register_snapshot
from .names import (
    AGGREGATOR_REGISTER,
    CAMERA_SIM_REGISTER,
    CONSUMER_REGISTER,
    PROCESSOR_REGISTER,
    PRODUCER_REGISTER,
)

__all__ = [
    "AGGREGATOR_REGISTER",
    "CAMERA_SIM_REGISTER",
    "CONSUMER_REGISTER",
    "PROCESSOR_REGISTER",
    "PRODUCER_REGISTER",
    "create_registers",
    "load_register_snapshot",
    "save_register_snapshot",
]
