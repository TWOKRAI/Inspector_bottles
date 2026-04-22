# multiprocess_prototype/backend/processes/__init__.py
"""Реализации процессов (class_path в proc_dict). Ленивые импорты — без циклов с configs/modules."""

from typing import Any

__all__ = [
    "UnifiedCameraProcess",
    "ProcessorProcess",
    "RendererProcess",
    "RobotSimulatorProcess",
    "GuiProcess",
    "DatabaseProcess",
]


def __getattr__(name: str) -> Any:
    if name == "UnifiedCameraProcess":
        from .camera.process import UnifiedCameraProcess

        return UnifiedCameraProcess
    if name == "ProcessorProcess":
        from .processor.process import ProcessorProcess

        return ProcessorProcess
    if name == "RendererProcess":
        from .render.process import RendererProcess

        return RendererProcess
    if name == "RobotSimulatorProcess":
        from .robot_simulator.robot_simulator_process import RobotSimulatorProcess

        return RobotSimulatorProcess
    if name == "GuiProcess":
        from .gui.gui_process import GuiProcess

        return GuiProcess
    if name == "DatabaseProcess":
        from .database.database_process import DatabaseProcess

        return DatabaseProcess
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
