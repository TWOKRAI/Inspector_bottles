# multiprocess_prototype\configs\camera_config.py
"""
Конфигурация процесса захвата видео (CameraProcess).

ProcessConfigBase + FieldMeta. class_path_from_type, ProcessPriorityLevel, memory.
"""

from typing import Annotated, Optional

from multiprocess_framework.refactored.modules.data_schema_module import (
    FieldMeta,
    register_schema,
)
from multiprocess_framework.refactored.modules.process_module import ProcessPriorityLevel

from multiprocess_prototype.configs.base_config import ProcessConfigBase, class_path_from_type
from multiprocess_prototype.processes.camera_process import CameraProcess


@register_schema("CameraConfig")
class CameraConfig(ProcessConfigBase):
    """Конфигурация процесса захвата видео."""

    process_name: str = "camera"
    class_path: str = class_path_from_type(CameraProcess)
    priority: ProcessPriorityLevel = ProcessPriorityLevel.HIGH
    fps: Annotated[int, FieldMeta("Частота кадров", min=1, max=120)] = 25
    resolution_width: Annotated[int, FieldMeta("Ширина кадра", min=320, max=1920)] = 640
    resolution_height: Annotated[int, FieldMeta("Высота кадра", min=240, max=1080)] = 480
    device_id: Annotated[int, FieldMeta("ID камеры", min=0, max=10)] = 0
    use_simulator: bool = False  # True = FrameGenerator, False = WebcamCapture (веб-камера)
    simulator_image_path: Optional[str] = None  # Путь к изображению для имитации; None = tests/test_image.png

    @property
    def memory(self) -> dict:
        """Короткий формат: (h, w, c) → фреймворк разворачивает в (1, (h,w,c), "uint8")."""
        return {"camera_frame": (self.resolution_height, self.resolution_width, 3), "coll": 2}

