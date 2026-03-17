# multiprocess_prototype\configs\gui_config.py
"""
Конфигурация GUI-процесса (GuiProcess).

ProcessConfigBase + FieldMeta. class_path_from_type.
"""

from typing import Annotated

from multiprocess_framework.refactored.modules.data_schema_module import (
    FieldMeta,
    register_schema,
)

from multiprocess_prototype.configs.base_config import ProcessConfigBase, class_path_from_type
from multiprocess_prototype.processes.gui_process import GuiProcess


@register_schema("GuiConfig")
class GuiConfig(ProcessConfigBase):
    """Конфигурация GUI-процесса."""

    process_name: str = "gui"
    class_path: str = class_path_from_type(GuiProcess)
    window_title: str = "Inspector Prototype"
    window_width: Annotated[
        int, FieldMeta("Ширина окна", min=400, max=1920)
    ] = 1024
    window_height: Annotated[
        int, FieldMeta("Высота окна", min=300, max=1080)
    ] = 768
    poll_interval_ms: Annotated[
        int, FieldMeta("Интервал опроса сообщений, мс", min=5, max=100)
    ] = 16
