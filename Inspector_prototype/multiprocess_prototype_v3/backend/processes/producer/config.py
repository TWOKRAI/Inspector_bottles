# multiprocess_prototype_v3/backend/processes/producer/config.py
"""Конфиг процесса producer."""

from __future__ import annotations

from multiprocess_framework.modules.data_schema_module import register_schema

from multiprocess_prototype_v3.backend.configs.base_config import (
    ProcessConfigBase,
    class_path_from_type,
)
from multiprocess_prototype_v3.registers.boot import producer_boot_values

from .process import ProducerProcess

_BOOT = producer_boot_values()


@register_schema("ProducerConfigV3")
class ProducerConfig(ProcessConfigBase):
    process_name: str = "producer"
    class_path: str = class_path_from_type(ProducerProcess)
    interval: float = _BOOT["interval"]
    message_prefix: str = _BOOT["message_prefix"]
    enabled: bool = _BOOT["enabled"]
    managers_preset: str = "standard"
