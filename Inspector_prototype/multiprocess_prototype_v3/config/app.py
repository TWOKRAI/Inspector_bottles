"""Root application config: aggregates all process configs."""

from __future__ import annotations

from multiprocess_framework.modules.data_schema_module import SchemaBase
from multiprocess_framework.modules.process_module import ProcessLaunchConfig

from multiprocess_prototype_v3.services.camera.config import CameraConfig
from multiprocess_prototype_v3.services.database.config import DatabaseConfig
from multiprocess_prototype_v3.services.gui.config import GuiConfig
from multiprocess_prototype_v3.services.processor.config import ProcessorConfig
from multiprocess_prototype_v3.services.renderer.config import RendererConfig
from multiprocess_prototype_v3.services.robot.config import RobotConfig

from .logging import LoggingConfig


class AppConfig(SchemaBase):
    """Top-level application configuration."""

    logging: LoggingConfig = LoggingConfig()
    camera: CameraConfig = CameraConfig()
    processor: ProcessorConfig = ProcessorConfig()
    renderer: RendererConfig = RendererConfig()
    robot: RobotConfig = RobotConfig()
    database: DatabaseConfig = DatabaseConfig()
    gui: GuiConfig = GuiConfig()
    stop_timeout: float = 5.0

    def all_process_configs(self) -> list[ProcessLaunchConfig]:
        return [
            self.camera,
            self.processor,
            self.renderer,
            self.robot,
            self.database,
            self.gui,
        ]
