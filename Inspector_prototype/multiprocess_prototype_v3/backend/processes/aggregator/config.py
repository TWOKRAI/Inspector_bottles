# multiprocess_prototype_v3/backend/processes/aggregator/config.py
"""Конфиг aggregator."""

from multiprocess_framework.modules.data_schema_module import register_schema

from multiprocess_prototype_v3.backend.configs.base_config import (
    ProcessConfigBase,
    class_path_from_type,
)
from multiprocess_prototype_v3.registers.boot import aggregator_boot_values

from .process import AggregatorProcess

_BOOT = aggregator_boot_values()


@register_schema("AggregatorConfigV3")
class AggregatorConfig(ProcessConfigBase):
    process_name: str = "aggregator"
    class_path: str = class_path_from_type(AggregatorProcess)
    report_interval: float = _BOOT["report_interval"]
    persist_detections: bool = False
    managers_preset: str = "pipeline"
