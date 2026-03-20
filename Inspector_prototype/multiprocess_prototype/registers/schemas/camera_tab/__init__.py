# -*- coding: utf-8 -*-
"""
Синхронизируемые регистры фичи «Камера».
"""
from .boot import camera_process_boot_values
from .camera import CAMERA_ROUTING, CameraRegisters
from .names import CAMERA_REGISTER

__all__ = [
    "CAMERA_REGISTER",
    "CAMERA_ROUTING",
    "CameraRegisters",
    "camera_process_boot_values",
]
