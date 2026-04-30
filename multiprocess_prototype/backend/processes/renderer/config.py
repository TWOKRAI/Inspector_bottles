"""Renderer service configuration."""

from __future__ import annotations

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.process_module import ProcessLaunchConfig


@register_schema("RendererConfigV3")
class RendererConfig(ProcessLaunchConfig):
    process_name: str = "renderer"
    process_class: str = "multiprocess_prototype.backend.processes.renderer.process.RendererProcess"
    output_dir: str = "./output_frames"
    resolution_width: int = 640
    resolution_height: int = 480
    show_original: bool = True
    show_mask: bool = True
    draw_contours: bool = True
    draw_bboxes: bool = True
    save_frames: bool = False

    @property
    def memory(self) -> dict:
        shape = (self.resolution_height, self.resolution_width, 3)
        return {"rendered_frame": shape, "mask_frame": shape, "coll": 2}
