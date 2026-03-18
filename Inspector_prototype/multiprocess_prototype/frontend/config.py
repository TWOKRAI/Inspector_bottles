# multiprocess_prototype\frontend\config.py
"""
GuiConfigFrontend — конфиг для GuiProcessFrontend (стек frontend_module).

Использование: в main.py заменить GuiConfig на GuiConfigFrontend.
"""

from typing import Annotated, Literal

from multiprocess_framework.refactored.modules.data_schema_module import (
    FieldMeta,
    register_schema,
)

from multiprocess_prototype.backend.configs.base_config import ProcessConfigBase, class_path_from_type
from multiprocess_prototype.frontend.process import GuiProcessFrontend


@register_schema("GuiConfigFrontend")
class GuiConfigFrontend(ProcessConfigBase):
    """Конфигурация GUI-процесса на frontend_module."""

    process_name: str = "gui"
    class_path: str = class_path_from_type(GuiProcessFrontend)
    camera_type: Literal["simulator", "webcam", "hikvision"] = "simulator"
    window_title: str = "Inspector Prototype (Frontend)"
    window_width: Annotated[int, FieldMeta("Ширина окна", min=400, max=1920)] = 1024
    window_height: Annotated[int, FieldMeta("Высота окна", min=300, max=1080)] = 600
    poll_interval_ms: Annotated[int, FieldMeta("Интервал опроса, мс", min=5, max=100)] = 16
