# -*- coding: utf-8 -*-
"""
Boot-значения для процесса камеры из CameraRegisters.
"""

from typing import Any

from .camera import CameraRegisters


def camera_process_boot_values() -> dict[str, Any]:
    """Поля камеры, совпадающие с CameraRegisters."""
    r = CameraRegisters()
    return {
        "camera_type": r.camera_type,
        "fps": r.fps,
        "resolution_width": r.resolution_width,
        "resolution_height": r.resolution_height,
        "device_id": r.device_id,
        "camera_index": r.camera_index,
        "hikvision_resolution_width": r.hikvision_resolution_width,
        "hikvision_resolution_height": r.hikvision_resolution_height,
    }
