"""Camera service configuration.

Каждая камера получает уникальный camera_id → уникальный process_name
и собственный набор SHM-слотов (ring-buffer из K кадров).
"""

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
    process_name: str = "camera_0"
    process_class: str = "multiprocess_prototype_v3.backend.processes.camera.process.CameraProcess"
    priority: ProcessPriorityLevel = ProcessPriorityLevel.HIGH

    # --- Идентификация камеры ---
    camera_id: int = 0
    camera_type: str = "simulator"

    # --- Ring-buffer (AD-6): количество SHM-слотов на камеру ---
    ring_buffer_size: int = 3

    # --- Общие параметры ---
    fps: int = 25
    resolution_width: int = 640
    resolution_height: int = 480

    # --- Webcam ---
    device_id: int = 0

    # --- Hikvision ---
    camera_index: int = 0
    hikvision_resolution_width: int = 1920
    hikvision_resolution_height: int = 1080
    hikvision_frame_rate: float = 25.0
    hikvision_exposure_time: float = 10000.0
    hikvision_gain: float = 0.0

    # --- File-source ---
    file_source_path: str = ""

    # --- Simulator ---
    use_simulator: bool = False
    simulator_image_path: str | None = None

    def model_post_init(self, __context: object) -> None:
        """process_name всегда соответствует camera_id."""
        # object.__setattr__ обходит validate_assignment (SchemaBase включает его)
        object.__setattr__(self, "process_name", f"camera_{self.camera_id}")

    @property
    def memory(self) -> dict:
        """SHM layout: ring-buffer из K слотов для данной камеры."""
        slot_name = f"camera_{self.camera_id}_frame"
        return {slot_name: (CAMERA_SHM_HEIGHT, CAMERA_SHM_WIDTH, 3), "coll": self.ring_buffer_size}

    def build(self) -> tuple[str, dict]:
        name, proc_dict = super().build()
        use_sim = self.use_simulator or (self.camera_type == "simulator")
        proc_dict["config"]["use_simulator"] = use_sim
        return name, proc_dict
