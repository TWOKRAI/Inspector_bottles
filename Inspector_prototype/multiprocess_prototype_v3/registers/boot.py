# multiprocess_prototype_v3/registers/boot.py
"""Значения по умолчанию регистров → boot полей конфигов."""

from __future__ import annotations

from typing import Any, Dict

from .aggregator import AggregatorRegisters
from .camera_sim import CameraSimRegisters
from .processor_registers import ProcessorRegisters
from .producer import ProducerRegisters


def producer_boot_values() -> Dict[str, Any]:
    return ProducerRegisters().model_dump()


def camera_sim_boot_values() -> Dict[str, Any]:
    return CameraSimRegisters().model_dump()


def processor_boot_values() -> Dict[str, Any]:
    return ProcessorRegisters().model_dump()


def aggregator_boot_values() -> Dict[str, Any]:
    return AggregatorRegisters().model_dump()
