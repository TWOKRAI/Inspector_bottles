"""Camera domain: schemas, type policy, Hikvision helpers."""

from .hikvision_params import HikvisionParamRow, build_hikvision_param_rows
from .policy import (
    CAMERA_TYPES,
    CAMERA_TYPE_LABELS,
    CameraTypeStr,
    DEFAULT_CAMERA_TYPE,
    SUPPORTS_ENUM,
    SUPPORTS_HARDWARE_HANDOFF,
    WEBCAM_ENUM_DEFAULT_MAX_INDEX,
    WEBCAM_ENUM_HARD_CAP,
)
from .schemas import (
    BaseCameraRegisters,
    GuiCameraRegisters,
    HikvisionCameraRegisters,
    WebcamCameraRegisters,
)

__all__ = [
    "BaseCameraRegisters",
    "WebcamCameraRegisters",
    "HikvisionCameraRegisters",
    "GuiCameraRegisters",
    "CameraTypeStr",
    "CAMERA_TYPES",
    "DEFAULT_CAMERA_TYPE",
    "CAMERA_TYPE_LABELS",
    "SUPPORTS_ENUM",
    "SUPPORTS_HARDWARE_HANDOFF",
    "WEBCAM_ENUM_DEFAULT_MAX_INDEX",
    "WEBCAM_ENUM_HARD_CAP",
    "HikvisionParamRow",
    "build_hikvision_param_rows",
]
