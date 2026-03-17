# -*- coding: utf-8 -*-
"""
hikvision_camera_module — фасад и адаптер для Hikvision SDK.

Публичный API:
- HikvisionCameraFacade — простой синхронный фасад (enum, open, close, grab, capture_frame, parameters)
- HikvisionCameraProcessAdapter — ProcessModule-адаптер (lazy, требует multiprocess_framework)
- IHikvisionCameraFacade — контракт фасада

Оригинальный SDK (sdk_app) запускается без multiprocess_framework.
"""

from hikvision_camera_module.interfaces import IHikvisionCameraFacade
from hikvision_camera_module.core.facade import HikvisionCameraFacade

__all__ = [
    "IHikvisionCameraFacade",
    "HikvisionCameraFacade",
    "HikvisionCameraProcessAdapter",
]


def __getattr__(name: str):
    """Ленивая загрузка адаптера — только при явном импорте."""
    if name == "HikvisionCameraProcessAdapter":
        from hikvision_camera_module.adapters.process_adapter import HikvisionCameraProcessAdapter
        return HikvisionCameraProcessAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
