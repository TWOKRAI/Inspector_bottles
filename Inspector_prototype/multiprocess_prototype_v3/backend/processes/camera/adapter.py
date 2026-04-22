"""CameraAdapter — IPC/SHM facade для CameraService.

Phase 3: параметризация по camera_id — каждая камера пишет в свой SHM-слот
и включает camera_id в payload frame_ready.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from multiprocess_framework.modules.process_module import ProcessIO


class CameraAdapter:
    """Реализует CameraOutputPort через ProcessIO (IPC + SHM facade).

    camera_id определяет SHM region/slot и включается в frame_ready payload.
    """

    def __init__(self, process, camera_id: int = 0) -> None:
        self._io = ProcessIO(process)
        self._camera_id = camera_id
        # SHM naming convention: camera_{id} / camera_{id}_frame
        self._shm_region = f"camera_{camera_id}"
        self._shm_slot = f"camera_{camera_id}_frame"

    def send_frame_to_processor(self, data: dict) -> None:
        # Добавляем camera_id в payload для маршрутизации
        data_with_id = {**data, "camera_id": self._camera_id}
        self._io.send_data("processor", "frame_ready", data_with_id)

    def send_to_gui(self, msg_type: str, data: dict) -> None:
        data_with_id = {**data, "camera_id": self._camera_id}
        self._io.send_data("gui", msg_type, data_with_id)

    def write_frame_to_shm(
        self, frame: np.ndarray, frame_id: int, timestamp: float
    ) -> Optional[dict]:
        return self._io.write_frames_to_shm(self._shm_region, self._shm_slot, [frame])
