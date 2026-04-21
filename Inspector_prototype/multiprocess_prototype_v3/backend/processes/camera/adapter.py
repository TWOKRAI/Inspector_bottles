"""CameraAdapter — IPC/SHM facade для CameraService."""
from __future__ import annotations

from typing import Optional

import numpy as np

from multiprocess_framework.modules.process_module import ProcessIO


class CameraAdapter:
    """Реализует CameraOutputPort через ProcessIO (IPC + SHM facade)."""

    def __init__(self, process) -> None:
        self._io = ProcessIO(process)

    def send_frame_to_processor(self, data: dict) -> None:
        self._io.send_data("processor", "frame_ready", data)

    def send_to_gui(self, msg_type: str, data: dict) -> None:
        self._io.send_data("gui", msg_type, data)

    def write_frame_to_shm(
        self, frame: np.ndarray, frame_id: int, timestamp: float
    ) -> Optional[dict]:
        return self._io.write_frames_to_shm("camera", "camera_frame", [frame])
