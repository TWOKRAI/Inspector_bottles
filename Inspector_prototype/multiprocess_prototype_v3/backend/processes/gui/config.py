# multiprocess_prototype_v3/backend/processes/gui/config.py
"""Конфиг GUI-процесса v3."""

from multiprocess_framework.modules.data_schema_module import register_schema

from multiprocess_prototype_v3.backend.configs.base_config import (
    ProcessConfigBase,
    class_path_from_type,
)

from .process import GuiProcess


@register_schema("GuiConfigV3")
class GuiConfig(ProcessConfigBase):
    process_name: str = "gui"
    class_path: str = class_path_from_type(GuiProcess)
    managers_preset: str = "pipeline"
