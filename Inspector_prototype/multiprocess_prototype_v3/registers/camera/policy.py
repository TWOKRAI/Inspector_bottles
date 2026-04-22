"""Camera type policy: supported types, labels, constraints."""

from __future__ import annotations

from typing import Literal

CameraTypeStr = Literal["simulator", "webcam", "hikvision", "file"]

CAMERA_TYPES: tuple[str, ...] = ("simulator", "webcam", "hikvision", "file")
DEFAULT_CAMERA_TYPE: str = "simulator"
CAMERA_TYPE_LABELS: tuple[str, ...] = ("Simulator", "Webcam", "Hikvision", "File")

SUPPORTS_ENUM: tuple[str, ...] = ("webcam", "hikvision")
SUPPORTS_HARDWARE_HANDOFF: tuple[str, ...] = ("webcam", "hikvision")

WEBCAM_ENUM_DEFAULT_MAX_INDEX = 32
WEBCAM_ENUM_HARD_CAP = 64

__all__ = [
    "CameraTypeStr",
    "CAMERA_TYPES", "DEFAULT_CAMERA_TYPE", "CAMERA_TYPE_LABELS",
    "SUPPORTS_ENUM", "SUPPORTS_HARDWARE_HANDOFF",
    "WEBCAM_ENUM_DEFAULT_MAX_INDEX", "WEBCAM_ENUM_HARD_CAP",
]
