# multiprocess_prototype/backend/processes/__init__.py
"""Backend-процессы приложения."""

from .unified_camera_process import UnifiedCameraProcess
from .processor_process import ProcessorProcess
from .renderer_process import RendererProcess
from .robot_simulator_process import RobotSimulatorProcess
from .gui_process import GuiProcess
from .database_process import DatabaseProcess

__all__ = [
    "UnifiedCameraProcess",
    "ProcessorProcess",
    "RendererProcess",
    "RobotSimulatorProcess",
    "GuiProcess",
    "DatabaseProcess",
]
