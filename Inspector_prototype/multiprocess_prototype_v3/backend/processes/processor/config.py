# multiprocess_prototype_v3/backend/processes/processor/config.py
"""Конфиг processor."""

from multiprocess_framework.modules.data_schema_module import register_schema

from multiprocess_prototype_v3.backend.configs.base_config import (
    ProcessConfigBase,
    class_path_from_type,
)
from multiprocess_prototype_v3.registers.boot import processor_boot_values

from .process import ProcessorProcess

_BOOT = processor_boot_values()


@register_schema("ProcessorConfigV3")
class ProcessorConfig(ProcessConfigBase):
    process_name: str = "processor"
    class_path: str = class_path_from_type(ProcessorProcess)
    brightness_threshold: int = _BOOT["brightness_threshold"]
    enabled: bool = _BOOT["enabled"]
    managers_preset: str = "pipeline"
