"""Redirect: registers.schemas.camera_tab → registers.names + registers.hikvision_params."""

from multiprocess_prototype_v3.registers.names import CAMERA_REGISTER
from multiprocess_prototype_v3.registers.camera import CAMERA_ROUTING
from multiprocess_prototype_v3.registers.hikvision_params import (
    HikvisionParamRow,
    build_hikvision_param_rows,
)

__all__ = [
    "CAMERA_REGISTER",
    "CAMERA_ROUTING",
    "HikvisionParamRow",
    "build_hikvision_param_rows",
]
