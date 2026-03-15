"""
Конфигурация процесса захвата видео (CameraProcess).

ProcessConfigBase + FieldMeta для валидации параметров.
build() — HasBuild для process() / add_process().
"""

from typing import Annotated, Optional

from multiprocess_framework.refactored.modules.data_schema_module import (
    FieldMeta,
    register_schema,
)

from multiprocess_prototype.configs.base_config import ProcessConfigBase


@register_schema("CameraConfig")
class CameraConfig(ProcessConfigBase):
    """Конфигурация процесса захвата видео."""

    process_name: str = "camera"
    fps: Annotated[int, FieldMeta("Частота кадров", min=1, max=120)] = 25
    resolution_width: Annotated[int, FieldMeta("Ширина кадра", min=320, max=1920)] = 640
    resolution_height: Annotated[int, FieldMeta("Высота кадра", min=240, max=1080)] = 480
    device_id: Annotated[int, FieldMeta("ID камеры", min=0, max=10)] = 0
    use_simulator: bool = True  # True = FrameGenerator, False = cv2.VideoCapture
    simulator_image_path: Optional[str] = None  # Путь к изображению для имитации; None = tests/test_image.png

    def build(self) -> tuple[str, dict]:
        """HasBuild: (name, proc_dict) для launcher.add_process(*process(CameraConfig()))."""
        memory = {
            "names": {
                "camera_frame": (
                    1,
                    (self.resolution_height, self.resolution_width, 3),
                    "uint8",
                ),
            },
            "coll": 2,
        }
        proc_dict = self._build_proc_dict(
            "multiprocess_prototype.processes.camera_process.CameraProcess",
            priority="high",
            memory=memory,
        )
        return (self.process_name, proc_dict)
