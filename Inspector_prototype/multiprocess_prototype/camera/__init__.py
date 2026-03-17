# multiprocess_prototype/camera/__init__.py
"""Модуль камеры: бэкенды и единый процесс."""

from .backends import SimulatorBackend, WebcamBackend, HikvisionBackend
from .unified_camera_process import UnifiedCameraProcess

__all__ = [
    "SimulatorBackend",
    "WebcamBackend",
    "HikvisionBackend",
    "UnifiedCameraProcess",
]
