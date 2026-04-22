"""Создание бэкенда захвата. Типы — из camera_policy."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Callable, Optional

from multiprocess_prototype.camera_policy import CAMERA_TYPES, DEFAULT_CAMERA_TYPE
from multiprocess_prototype.backend.modules.camera.backends import (
    BaseCaptureBackend,
    HikvisionBackend,
    SimulatorBackend,
    WebcamBackend,
)


@dataclass
class CameraBackendParams:
    width: int
    height: int
    device_id: int
    camera_index: int
    hikvision_width: int
    hikvision_height: int
    simulator_image_path: Optional[str]
    send_to_gui: Callable[[str, dict], None]


_BACKENDS = {
    "simulator": lambda p: SimulatorBackend(p.width, p.height, image_path=p.simulator_image_path),
    "webcam": lambda p: WebcamBackend(p.width, p.height, device_id=p.device_id),
    "hikvision": None,  # специальная логика (Windows)
}


def create_camera_backend(camera_type: str, p: CameraBackendParams) -> BaseCaptureBackend:
    if camera_type not in CAMERA_TYPES:
        camera_type = DEFAULT_CAMERA_TYPE
    if camera_type == "hikvision":
        if sys.platform != "win32":
            p.send_to_gui(
                "status",
                {"status": "Hikvision only on Windows, using Simulator"},
            )
            return SimulatorBackend(p.width, p.height, image_path=p.simulator_image_path)
        return HikvisionBackend(
            p.camera_index,
            p.hikvision_width,
            p.hikvision_height,
            send_to_gui=p.send_to_gui,
        )
    factory = _BACKENDS.get(camera_type)
    if factory:
        return factory(p)
    return SimulatorBackend(p.width, p.height)
