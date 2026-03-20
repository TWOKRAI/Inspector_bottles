"""Создание бэкенда захвата (simulator / webcam / hikvision)."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Callable, Optional

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


def create_camera_backend(camera_type: str, p: CameraBackendParams) -> BaseCaptureBackend:
    if camera_type == "simulator":
        return SimulatorBackend(p.width, p.height, image_path=p.simulator_image_path)
    if camera_type == "webcam":
        return WebcamBackend(p.width, p.height, device_id=p.device_id)
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
    return SimulatorBackend(p.width, p.height)
