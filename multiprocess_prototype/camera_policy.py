# multiprocess_prototype/camera_policy.py
"""
Единый источник правды для типов камеры и политик enum/handoff.

Добавление нового типа: правка только здесь + backend_factory + callbacks_map.
Использовать: from multiprocess_prototype.camera_policy import CAMERA_TYPES, ...
"""
from __future__ import annotations

from typing import Literal, Tuple

# --- Типы камер ---
CameraTypeStr = Literal["simulator", "webcam", "hikvision"]
CAMERA_TYPES: Tuple[CameraTypeStr, ...] = ("simulator", "webcam", "hikvision")
DEFAULT_CAMERA_TYPE: CameraTypeStr = "simulator"
# Отображаемые подписи для UI (порядок = CAMERA_TYPES)
CAMERA_TYPE_LABELS: Tuple[str, ...] = ("Simulator", "Webcam", "Hikvision")

# Типы с перечислением устройств (enum_devices)
SUPPORTS_ENUM: Tuple[str, ...] = ("webcam", "hikvision")

# Типы, требующие handoff при переключении (USB/драйвер)
SUPPORTS_HARDWARE_HANDOFF: Tuple[str, ...] = ("webcam", "hikvision")

# --- Enum Webcam ---
WEBCAM_ENUM_DEFAULT_MAX_INDEX = 32
WEBCAM_ENUM_HARD_CAP = 64


def is_valid_camera_type(t: str) -> bool:
    return t in CAMERA_TYPES


def supports_enum(camera_type: str) -> bool:
    return camera_type in SUPPORTS_ENUM


def supports_hardware_handoff(camera_type: str) -> bool:
    return camera_type in SUPPORTS_HARDWARE_HANDOFF
