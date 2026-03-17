# multiprocess_prototype\configs\renderer_config.py
"""
Конфигурация процесса отрисовки (RendererProcess).

ProcessConfigBase + FieldMeta. class_path_from_type, memory.
"""

from typing import Annotated

from multiprocess_framework.refactored.modules.data_schema_module import (
    FieldMeta,
    register_schema,
)

from multiprocess_prototype.configs.base_config import ProcessConfigBase, class_path_from_type
from multiprocess_prototype.processes.renderer_process import RendererProcess


@register_schema("RendererConfig")
class RendererConfig(ProcessConfigBase):
    """Конфигурация процесса отрисовки."""

    process_name: str = "renderer"
    class_path: str = class_path_from_type(RendererProcess)
    output_dir: str = "./output_frames"
    save_frames: bool = False  # сохранять кадры на диск
    draw_bboxes: bool = True  # рисовать bounding boxes
    resolution_width: int = 640
    resolution_height: int = 480

    @property
    def memory(self) -> dict:
        shape = (self.resolution_height, self.resolution_width, 3)
        return {"rendered_frame": shape, "mask_frame": shape, "coll": 2}
