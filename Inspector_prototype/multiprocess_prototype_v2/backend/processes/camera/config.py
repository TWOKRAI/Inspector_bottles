# multiprocess_prototype_v2/backend/processes/camera/config.py
"""Конфигурация процесса захвата видео (UnifiedCameraProcess).

Изменяемые параметры — в ``registers.gui_camera_registers.GuiCameraRegisters``; boot из ``registers.boot``.
"""

from typing import Optional

from multiprocess_prototype_v2.registers.camera import CameraTypeStr, DEFAULT_CAMERA_TYPE

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.process_module import ProcessPriorityLevel

from multiprocess_prototype_v2.backend.configs.base_config import ProcessConfigBase, class_path_from_type
from multiprocess_prototype_v2.backend.modules.camera.constants import (
    CAMERA_SHM_HEIGHT,
    CAMERA_SHM_WIDTH,
)
from multiprocess_prototype_v2.registers.boot import camera_process_boot_values

from .process import UnifiedCameraProcess

_BOOT = camera_process_boot_values()


@register_schema("CameraConfig")
class CameraConfig(ProcessConfigBase):
    """Конфигурация процесса захвата видео."""

    process_name: str = "camera"
    class_path: str = class_path_from_type(UnifiedCameraProcess)
    priority: ProcessPriorityLevel = ProcessPriorityLevel.HIGH
    camera_type: CameraTypeStr = _BOOT.get("camera_type", DEFAULT_CAMERA_TYPE)
    fps: int = _BOOT["fps"]
    resolution_width: int = _BOOT["resolution_width"]
    resolution_height: int = _BOOT["resolution_height"]
    device_id: int = _BOOT["device_id"]
    camera_index: int = _BOOT["camera_index"]
    hikvision_resolution_width: int = _BOOT["hikvision_resolution_width"]
    hikvision_resolution_height: int = _BOOT["hikvision_resolution_height"]
    hikvision_frame_rate: float = _BOOT["hikvision_frame_rate"]
    hikvision_exposure_time: float = _BOOT["hikvision_exposure_time"]
    hikvision_gain: float = _BOOT["hikvision_gain"]
    use_simulator: bool = False
    simulator_image_path: Optional[str] = None

    def build(self) -> tuple[str, dict]:
        from multiprocess_prototype_v2.backend.configs.proc_assembly import build_proc_dict

        use_sim = self.use_simulator or (self.camera_type == DEFAULT_CAMERA_TYPE)
        proc_dict = build_proc_dict(self)
        proc_dict["config"] = {
            **proc_dict.get("config", {}),
            "use_simulator": use_sim,
            "camera_type": self.camera_type,
        }
        return (self.process_name, proc_dict)

    @property
    def memory(self) -> dict:
        return {"camera_frame": (CAMERA_SHM_HEIGHT, CAMERA_SHM_WIDTH, 3), "coll": 2}
