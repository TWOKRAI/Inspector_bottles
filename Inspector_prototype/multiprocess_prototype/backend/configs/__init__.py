# multiprocess_prototype\backend\configs\__init__.py
"""
Конфигурационные схемы Inspector Prototype (backend).

Все схемы наследуют SchemaBase из data_schema_module.
"""

from .app_config import get_log_dir, get_default_managers_config
from .base_config import ProcessConfigBase, class_path_from_type
from .camera_config import CameraConfig
from .processor_config import ProcessorConfig
from .renderer_config import RendererConfig
from .robot_config import RobotConfig
from .gui_config import GuiConfig
from .database_config import DatabaseConfig

__all__ = [
    "get_log_dir",
    "get_default_managers_config",
    "ProcessConfigBase",
    "class_path_from_type",
    "CameraConfig",
    "ProcessorConfig",
    "RendererConfig",
    "RobotConfig",
    "GuiConfig",
    "DatabaseConfig",
]
