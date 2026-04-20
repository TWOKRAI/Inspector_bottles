"""Camera service configuration."""

from __future__ import annotations

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.process_module import (
    ProcessLaunchConfig,
    ProcessPriorityLevel,
)
from multiprocess_prototype_v3.services.camera.constants import (
    CAMERA_SHM_HEIGHT,
    CAMERA_SHM_WIDTH,
)


@register_schema("CameraConfigV3")
class CameraConfig(ProcessLaunchConfig):
    process_name: str = "camera"
    process_class: str = "multiprocess_prototype_v3.backend.processes.camera.process.CameraProcess"
    priority: ProcessPriorityLevel = ProcessPriorityLevel.HIGH
    camera_type: str = "simulator"
    fps: int = 25
    resolution_width: int = 640
    resolution_height: int = 480
    device_id: int = 0
    camera_index: int = 0
    hikvision_resolution_width: int = 1920
    hikvision_resolution_height: int = 1080
    hikvision_frame_rate: float = 25.0
    hikvision_exposure_time: float = 10000.0
    hikvision_gain: float = 0.0
    use_simulator: bool = False
    simulator_image_path: str | None = None

    @property
    def memory(self) -> dict:
        return {"camera_frame": (CAMERA_SHM_HEIGHT, CAMERA_SHM_WIDTH, 3), "coll": 2}

    def build(self) -> tuple[str, dict]:
        name, proc_dict = super().build()
        use_sim = self.use_simulator or (self.camera_type == "simulator")
        proc_dict["config"]["use_simulator"] = use_sim
        return name, proc_dict
