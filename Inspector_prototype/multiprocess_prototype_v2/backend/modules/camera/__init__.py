"""Инфраструктура камеры. Тяжёлые фабрики подгружаются лениво — без циклов с configs."""

from __future__ import annotations

import importlib
from typing import Any

from .constants import CAMERA_SHM_HEIGHT, CAMERA_SHM_WIDTH
from .resize import resize_frame_for_shm

__all__ = [
    "BaseCaptureBackend",
    "CAMERA_SHM_HEIGHT",
    "CAMERA_SHM_WIDTH",
    "CameraBackendParams",
    "create_camera_backend",
    "HikvisionBackend",
    "resize_frame_for_shm",
    "SimulatorBackend",
    "WebcamBackend",
]


def __getattr__(name: str) -> Any:
    if name in ("CameraBackendParams", "create_camera_backend"):
        mod = importlib.import_module(".backend_factory", __name__)
        return getattr(mod, name)
    if name in (
        "BaseCaptureBackend",
        "HikvisionBackend",
        "SimulatorBackend",
        "WebcamBackend",
    ):
        mod = importlib.import_module(".backends", __name__)
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
