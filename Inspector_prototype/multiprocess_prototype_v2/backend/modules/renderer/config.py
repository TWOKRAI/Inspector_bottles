# multiprocess_prototype_v2/backend/modules/renderer/config.py
"""
Конфигурация процесса отрисовки.

Флаги show_* / draw_* — из ``RendererRegisters`` через ``registers.boot.renderer_process_boot_values``.
"""

from multiprocess_framework.modules.data_schema_module import register_schema

from multiprocess_prototype_v2.backend.configs.base_config import ProcessConfigBase
from multiprocess_prototype_v2.registers.boot import renderer_process_boot_values

_RBOOT = renderer_process_boot_values()

_RENDERER_CLASS_PATH = (
    "multiprocess_prototype_v2.backend.processes.render.process.RendererProcess"
)


@register_schema("RendererConfig")
class RendererConfig(ProcessConfigBase):
    """Конфигурация процесса отрисовки."""

    process_name: str = "renderer"
    class_path: str = _RENDERER_CLASS_PATH
    output_dir: str = "./output_frames"
    resolution_width: int = 640
    resolution_height: int = 480

    show_original: bool = _RBOOT["show_original"]
    show_mask: bool = _RBOOT["show_mask"]
    draw_contours: bool = _RBOOT["draw_contours"]
    draw_bboxes: bool = _RBOOT["draw_bboxes"]
    save_frames: bool = _RBOOT["save_frames"]

    @property
    def memory(self) -> dict:
        shape = (self.resolution_height, self.resolution_width, 3)
        return {"rendered_frame": shape, "mask_frame": shape, "coll": 2}
