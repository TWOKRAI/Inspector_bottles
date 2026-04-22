"""CameraAdapter — IPC/SHM facade для CameraService.

Phase 3: параметризация по camera_id + ring-buffer (AD-6).
Каждая камера пишет в свой ring-buffer из K SHM-слотов.
frame_ready payload содержит camera_id, seq_id, slot_index.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import numpy as np

from multiprocess_framework.modules.process_module import ProcessIO

if TYPE_CHECKING:
    from multiprocess_prototype_v3.backend.shm.ring_buffer import RingBufferWriter


class CameraAdapter:
    """Реализует CameraOutputPort через ProcessIO (IPC) + RingBufferWriter (SHM).

    camera_id определяет SHM region/slot.
    ring_buffer обеспечивает безопасный round-robin fan-out.
    """

    def __init__(
        self,
        process,
        camera_id: int = 0,
        ring_buffer: Optional["RingBufferWriter"] = None,
    ) -> None:
        self._io = ProcessIO(process)
        self._camera_id = camera_id
        self._ring_buffer = ring_buffer
        # Fallback SHM naming (если ring_buffer не задан)
        self._shm_region = f"camera_{camera_id}"
        self._shm_slot = f"camera_{camera_id}_frame"

    def send_frame_to_processor(self, data: dict) -> None:
        # camera_id в payload для маршрутизации
        data_with_id = {**data, "camera_id": self._camera_id}
        self._io.send_data("processor", "frame_ready", data_with_id)

    def send_to_gui(self, msg_type: str, data: dict) -> None:
        data_with_id = {**data, "camera_id": self._camera_id}
        self._io.send_data("gui", msg_type, data_with_id)

    def write_frame_to_shm(
        self, frame: np.ndarray, frame_id: int, timestamp: float
    ) -> Optional[dict]:
        """Записать кадр в SHM через ring-buffer (AD-6) или fallback ProcessIO."""
        if self._ring_buffer is not None:
            slot_index, seq_id = self._ring_buffer.write(frame)
            return {
                "shm_name": self._shm_slot,
                "shm_index": slot_index,
                "seq_id": seq_id,
            }
        # Fallback без ring-buffer (обратная совместимость)
        return self._io.write_frames_to_shm(self._shm_region, self._shm_slot, [frame])
