"""Root application config: aggregates all process configs.

Phase 3: поддержка гетерогенного списка камер (webcam + hikvision + simulator + file
в одном запуске). Список камер приходит из рецепта или строится по settings profile.
"""

from __future__ import annotations

from multiprocess_framework.modules.data_schema_module import SchemaBase
from multiprocess_framework.modules.process_module import ProcessLaunchConfig

from multiprocess_prototype_v3.backend.processes.camera.config import CameraConfig
from multiprocess_prototype_v3.backend.processes.database.config import DatabaseConfig
from multiprocess_prototype_v3.backend.processes.gui.config import GuiConfig
from multiprocess_prototype_v3.backend.processes.processor.config import ProcessorConfig
from multiprocess_prototype_v3.backend.processes.renderer.config import RendererConfig
from multiprocess_prototype_v3.backend.processes.robot.config import RobotConfig

from .logging import LoggingConfig


class AppConfig(SchemaBase):
    """Top-level application configuration.

    cameras — гетерогенный список: каждая камера может быть своего типа
    (webcam, hikvision, simulator, file). Если пуст — fallback на 1 симулятор.
    """

    logging: LoggingConfig = LoggingConfig()
    cameras: list[CameraConfig] = []
    processor: ProcessorConfig = ProcessorConfig()
    renderer: RendererConfig = RendererConfig()
    robot: RobotConfig = RobotConfig()
    database: DatabaseConfig = DatabaseConfig()
    gui: GuiConfig = GuiConfig()
    stop_timeout: float = 5.0

    def model_post_init(self, __context: object) -> None:
        """Fallback: если cameras пуст — создаём 1 симулятор (обратная совместимость)."""
        if not self.cameras:
            object.__setattr__(self, "cameras", [CameraConfig(camera_id=0)])

    def all_process_configs(self) -> list[ProcessLaunchConfig]:
        """Все конфиги процессов: N камер + processor + renderer + robot + database + gui."""
        return [
            *self.cameras,
            self.processor,
            self.renderer,
            self.robot,
            self.database,
            self.gui,
        ]


def build_cameras_from_profile(
    camera_count: int = 1,
    camera_source_type: str = "simulator",
    ring_buffer_size: int = 3,
) -> list[CameraConfig]:
    """Построить однородный список камер из settings profile (Phase 0 совместимость).

    Для гетерогенных камер — передавай cameras напрямую из рецепта.
    """
    return [
        CameraConfig(
            camera_id=i,
            camera_type=camera_source_type,
            ring_buffer_size=ring_buffer_size,
        )
        for i in range(camera_count)
    ]


def build_cameras_from_recipe(camera_dicts: list[dict]) -> list[CameraConfig]:
    """Построить гетерогенный список камер из рецепта.

    Каждый dict — полный набор параметров CameraConfig:
    [{"camera_id": 0, "camera_type": "webcam", "device_id": 0, "fps": 30}, ...]
    """
    cameras = []
    for i, d in enumerate(camera_dicts):
        # camera_id из рецепта или по порядку
        if "camera_id" not in d:
            d = {**d, "camera_id": i}
        cameras.append(CameraConfig(**d))
    return cameras
