"""DEPRECATED: use registers.camera and registers.constants directly."""

from multiprocess_prototype_v3.registers.camera import HikvisionParamRow, build_hikvision_param_rows
from multiprocess_prototype_v3.registers.camera.schemas import GuiCameraRegisters
from multiprocess_prototype_v3.registers.constants import CAMERA_REGISTER, CAMERA_ROUTING

__all__ = [
    "CAMERA_REGISTER",
    "CAMERA_ROUTING",
    "GuiCameraRegisters",
    "HikvisionParamRow",
    "build_hikvision_param_rows",
]
