# -*- coding: utf-8 -*-
"""
Канонические схемы пайплайна и политика камеры (v3).

Новые модули сюда **не** добавлять — см. ``README.md`` в этой папке.
Состав ``RegistersManager`` и GUI-маршрутизация — пакет ``app_registers``.
"""

from __future__ import annotations

from .camera import BaseCameraRegisters, HikvisionCameraRegisters, WebcamCameraRegisters
from .pipeline import CameraNode, Pipeline, RegionNode

__all__ = [
    "Pipeline",
    "CameraNode",
    "BaseCameraRegisters",
    "WebcamCameraRegisters",
    "HikvisionCameraRegisters",
    "RegionNode",
]
