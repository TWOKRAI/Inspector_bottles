# multiprocess_prototype_v3/backend/processes/camera_sim/config.py
"""Конфиг camera_sim."""

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.process_module import ProcessPriorityLevel

from multiprocess_prototype_v3.backend.configs.base_config import (
    ProcessConfigBase,
    class_path_from_type,
)
from multiprocess_prototype_v3.registers.boot import camera_sim_boot_values

from .process import CameraSimProcess

_BOOT = camera_sim_boot_values()


@register_schema("CameraSimConfigV3")
class CameraSimConfig(ProcessConfigBase):
    process_name: str = "camera_sim"
    class_path: str = class_path_from_type(CameraSimProcess)
    priority: ProcessPriorityLevel = ProcessPriorityLevel.HIGH
    fps: int = _BOOT["fps"]
    resolution_width: int = _BOOT["resolution_width"]
    resolution_height: int = _BOOT["resolution_height"]
    frame_color: str = _BOOT["frame_color"]
    managers_preset: str = "pipeline"

    @property
    def memory(self) -> dict:
        h = self.resolution_height
        w = self.resolution_width
        return {"camera_frame": (h, w, 3), "coll": 2}
