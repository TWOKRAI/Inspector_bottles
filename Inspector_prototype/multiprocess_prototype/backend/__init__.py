# multiprocess_prototype/backend/__init__.py
"""Бэкенды захвата кадров для UnifiedCameraProcess."""

from .backends import SimulatorBackend, WebcamBackend, HikvisionBackend

__all__ = [
    "SimulatorBackend",
    "WebcamBackend",
    "HikvisionBackend",
]
