# multiprocess_prototype\processes\__init__.py
"""Процессы приложения."""

from .camera_process import CameraProcess
from .processor_process import ProcessorProcess
from .renderer_process import RendererProcess
from .robot_simulator_process import RobotSimulatorProcess
from .gui_process import GuiProcess

__all__ = [
    "CameraProcess",
    "ProcessorProcess",
    "RendererProcess",
    "RobotSimulatorProcess",
    "GuiProcess",
]
