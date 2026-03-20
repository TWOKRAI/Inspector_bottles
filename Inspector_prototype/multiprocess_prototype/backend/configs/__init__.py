# multiprocess_prototype/backend/configs/__init__.py
"""
Общие конфиги backend: base_config, app_config.

Схемы процессов — прямые импорты (без полного `modules.__init__`, меньше циклов).
"""

from .app_config import get_log_dir, get_default_managers_config, merge_managers
from .base_config import ProcessConfigBase, class_path_from_type

from multiprocess_prototype.backend.modules.processor_frame.config import ProcessorConfig
from multiprocess_prototype.backend.modules.renderer.config import RendererConfig
from multiprocess_prototype.backend.processes.camera.config import CameraConfig
from multiprocess_prototype.backend.processes.database.database_config import DatabaseConfig
from multiprocess_prototype.backend.processes.gui.gui_config import GuiConfig
from multiprocess_prototype.backend.processes.robot_simulator.robot_config import RobotConfig

__all__ = [
    "get_log_dir",
    "get_default_managers_config",
    "merge_managers",
    "ProcessConfigBase",
    "class_path_from_type",
    "CameraConfig",
    "ProcessorConfig",
    "RendererConfig",
    "RobotConfig",
    "GuiConfig",
    "DatabaseConfig",
]
