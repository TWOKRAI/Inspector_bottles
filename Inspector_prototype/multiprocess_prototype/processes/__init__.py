# multiprocess_prototype/processes/__init__.py
"""Процессы приложения."""

from .unified_camera_process import UnifiedCameraProcess
from .processor_process import ProcessorProcess
from .renderer_process import RendererProcess
from .robot_simulator_process import RobotSimulatorProcess
from .gui_process import GuiProcess

__all__ = [
    "UnifiedCameraProcess",
    "ProcessorProcess",
    "RendererProcess",
    "RobotSimulatorProcess",
    "GuiProcess",
]
