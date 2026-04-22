# -*- coding: utf-8 -*-
"""
Канонические схемы пайплайна, камера, GUI-регистры и фабрика RegistersManager.

См. ``README.md``. Маршрутизация GUI-команд: ``registers.command_routing``.
"""

from __future__ import annotations

from .camera import BaseCameraRegisters, HikvisionCameraRegisters, WebcamCameraRegisters
from .command_routing import resolve_command_targets
from .factory import create_registers
from .names import CAMERA_REGISTER, PROCESSOR_REGISTER, RENDERER_REGISTER
from .pipeline import CameraNode, Pipeline, RegionNode

__all__ = [
    "CAMERA_REGISTER",
    "PROCESSOR_REGISTER",
    "RENDERER_REGISTER",
    "Pipeline",
    "CameraNode",
    "BaseCameraRegisters",
    "WebcamCameraRegisters",
    "HikvisionCameraRegisters",
    "RegionNode",
    "create_registers",
    "resolve_command_targets",
]
