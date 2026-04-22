"""Инфраструктура камеры (без конфига/процесса — они в `processes/camera`)."""

from .backend_factory import CameraBackendParams, create_camera_backend
from .backends import BaseCaptureBackend, HikvisionBackend, SimulatorBackend, WebcamBackend
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
