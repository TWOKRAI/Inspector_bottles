# multiprocess_prototype_v3/backend/processes/consumer/config.py
"""Конфиг процесса consumer."""

from typing import Optional

from multiprocess_framework.modules.data_schema_module import register_schema

from multiprocess_prototype_v3.backend.configs.base_config import (
    ProcessConfigBase,
    class_path_from_type,
)

from .process import ConsumerProcess


@register_schema("ConsumerConfigV3")
class ConsumerConfig(ProcessConfigBase):
    process_name: str = "consumer"
    class_path: str = class_path_from_type(ConsumerProcess)
    managers_preset: str = "standard"
    probe_path: Optional[str] = None
