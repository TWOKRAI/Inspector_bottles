"""hikvision_camera_module_2 -- рефакторинг модуля Hikvision камеры.

Чистая архитектура:
    sdk/    -- минимальные ctypes bindings к MVS SDK
    core/   -- бизнес-логика (camera state machine, discovery, parameters, converter)
    plugin/ -- плагин для multiprocess_prototype_2 (source plugin + registers)

Публичный API:
    HikvisionCamera       -- state machine камеры (core)
    HikvisionCameraPlugin -- source plugin для multiprocess_prototype_2
    HikvisionCameraConfig -- конфиг плагина
"""
from __future__ import annotations

from hikvision_camera_module_2.core.camera import HikvisionCamera, CameraState
from hikvision_camera_module_2.core.discovery import enum_devices, DeviceInfo
from hikvision_camera_module_2.core.parameters import CameraParameters
from hikvision_camera_module_2.core.converter import FrameConverter

__all__ = [
    "HikvisionCamera",
    "CameraState",
    "enum_devices",
    "DeviceInfo",
    "CameraParameters",
    "FrameConverter",
]


def __getattr__(name: str):
    """Ленивая загрузка plugin layer -- только при явном импорте.

    Позволяет использовать core/ без зависимости от multiprocess_framework.
    Plugin layer подтягивается только когда нужен:
        from hikvision_camera_module_2 import HikvisionCameraPlugin
    """
    if name == "HikvisionCameraPlugin":
        from hikvision_camera_module_2.plugin.plugin import HikvisionCameraPlugin
        return HikvisionCameraPlugin
    if name == "HikvisionCameraConfig":
        from hikvision_camera_module_2.plugin.config import HikvisionCameraConfig
        return HikvisionCameraConfig
    if name == "HikvisionCameraRegisters":
        from hikvision_camera_module_2.plugin.registers import HikvisionCameraRegisters
        return HikvisionCameraRegisters
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
