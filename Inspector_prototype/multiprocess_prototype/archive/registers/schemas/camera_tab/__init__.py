# -*- coding: utf-8 -*-
"""
Синхронизируемые регистры фичи «Камера».
"""
from .boot import camera_process_boot_values
from .camera import (
    CAMERA_ROUTING,
    CameraRegisters,
    HikvisionCameraRegisters,
    StandardCameraRegisters,
)
from .hikvision_param_rows import (
    API_KEY_TO_REGISTER_FIELD,
    HIKVISION_SET_PARAMETER_REGISTER_FIELDS,
    HikvisionParamRow,
    REGISTER_FIELD_TO_API_KEY,
    build_hikvision_param_rows,
)
from .names import CAMERA_REGISTER

__all__ = [
    "API_KEY_TO_REGISTER_FIELD",
    "CAMERA_REGISTER",
    "CAMERA_ROUTING",
    "CameraRegisters",
    "HikvisionCameraRegisters",
    "StandardCameraRegisters",
    "HIKVISION_SET_PARAMETER_REGISTER_FIELDS",
    "HikvisionParamRow",
    "REGISTER_FIELD_TO_API_KEY",
    "build_hikvision_param_rows",
    "camera_process_boot_values",
]
