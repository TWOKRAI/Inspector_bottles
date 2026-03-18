# multiprocess_prototype\configs\camera_config.py
"""
Конфигурация процесса захвата видео (UnifiedCameraProcess).

Единый процесс с переключением simulator | webcam | hikvision без перезапуска.
"""

from typing import Annotated, Literal, Optional

from multiprocess_framework.refactored.modules.data_schema_module import (
    FieldMeta,
    register_schema,
)
from multiprocess_framework.refactored.modules.process_module import ProcessPriorityLevel

from multiprocess_prototype.backend.configs.base_config import ProcessConfigBase, class_path_from_type
from multiprocess_prototype.backend.processes.unified_camera_process import UnifiedCameraProcess


@register_schema("CameraConfig")
class CameraConfig(ProcessConfigBase):
    """Конфигурация процесса захвата видео."""

    process_name: str = "camera"
    class_path: str = class_path_from_type(UnifiedCameraProcess)
    priority: ProcessPriorityLevel = ProcessPriorityLevel.HIGH
    camera_type: Literal["simulator", "webcam", "hikvision"] = "simulator"
    fps: Annotated[int, FieldMeta("Частота кадров", min=1, max=120)] = 25
    resolution_width: Annotated[int, FieldMeta("Ширина кадра", min=320, max=1920)] = 640
    resolution_height: Annotated[int, FieldMeta("Высота кадра", min=240, max=1080)] = 480
    device_id: Annotated[int, FieldMeta("ID камеры", min=0, max=10)] = 0
    camera_index: Annotated[int, FieldMeta("Индекс Hikvision камеры", min=0, max=10)] = 0
    hikvision_resolution_width: Annotated[int, FieldMeta("Ширина Hikvision", min=320, max=4096)] = 1920
    hikvision_resolution_height: Annotated[int, FieldMeta("Высота Hikvision", min=240, max=4096)] = 1080
    use_simulator: bool = False
    simulator_image_path: Optional[str] = None

    def build(self) -> tuple[str, dict]:
        """UnifiedCameraProcess — один класс, memory max размер для всех режимов."""
        priority_val = (
            self.priority.value if hasattr(self.priority, "value") else self.priority
        )
        use_sim = self.use_simulator or (self.camera_type == "simulator")
        proc_dict = self._build_proc_dict(
            self.class_path,
            queues=self.queues,
            priority=priority_val,
            memory=self.memory,
        )
        proc_dict["config"] = {
            **proc_dict.get("config", {}),
            "use_simulator": use_sim,
            "camera_type": self.camera_type,
        }
        return (self.process_name, proc_dict)

    @property
    def memory(self) -> dict:
        """Макс. размер (1920x1080) — единый для всех режимов, переключение без перезапуска."""
        return {"camera_frame": (1080, 1920, 3), "coll": 2}

