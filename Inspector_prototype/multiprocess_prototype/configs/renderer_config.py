"""
Конфигурация процесса отрисовки (RendererProcess).

ProcessConfigBase + FieldMeta для валидации параметров.
build() — HasBuild для process() / add_process().
"""

from typing import Annotated

from multiprocess_framework.refactored.modules.data_schema_module import (
    FieldMeta,
    register_schema,
)

from multiprocess_prototype.configs.base_config import ProcessConfigBase


@register_schema("RendererConfig")
class RendererConfig(ProcessConfigBase):
    """Конфигурация процесса отрисовки."""

    process_name: str = "renderer"
    output_dir: str = "./output_frames"
    save_frames: bool = False  # сохранять кадры на диск
    draw_bboxes: bool = True  # рисовать bounding boxes
    resolution_width: int = 640
    resolution_height: int = 480

    def build(self) -> tuple[str, dict]:
        """HasBuild: (name, proc_dict) для launcher.add_process(*process(RendererConfig()))."""
        memory = {
            "names": {
                "rendered_frame": (
                    1,
                    (self.resolution_height, self.resolution_width, 3),
                    "uint8",
                ),
                "mask_frame": (
                    1,
                    (self.resolution_height, self.resolution_width, 3),
                    "uint8",
                ),
            },
            "coll": 2,
        }
        proc_dict = self._build_proc_dict(
            "multiprocess_prototype.processes.renderer_process.RendererProcess",
            memory=memory,
        )
        return (self.process_name, proc_dict)
