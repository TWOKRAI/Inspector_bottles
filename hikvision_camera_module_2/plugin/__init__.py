"""Плагин Hikvision камеры для multiprocess_prototype_2."""
from __future__ import annotations

from .plugin import HikvisionCameraPlugin
from .config import HikvisionCameraConfig
from .registers import HikvisionCameraRegisters

__all__ = [
    "HikvisionCameraPlugin",
    "HikvisionCameraConfig",
    "HikvisionCameraRegisters",
]
