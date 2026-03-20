"""Инфраструктура камеры (без конфига/процесса — они в `processes/camera`)."""

from .backend_factory import CameraBackendParams, create_camera_backend
from .constants import CAMERA_SHM_HEIGHT, CAMERA_SHM_WIDTH
from .resize import resize_frame_for_shm

__all__ = [
    "CAMERA_SHM_HEIGHT",
    "CAMERA_SHM_WIDTH",
    "CameraBackendParams",
    "create_camera_backend",
    "resize_frame_for_shm",
]
