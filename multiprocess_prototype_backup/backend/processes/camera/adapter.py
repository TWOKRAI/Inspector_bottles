"""CameraAdapter — IPC/SHM facade для CameraService.

Phase 3: параметризация по camera_id + ring-buffer (AD-6).
Каждая камера пишет в свой ring-buffer из K SHM-слотов.
frame_ready payload содержит camera_id, seq_id, slot_index.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from multiprocess_framework.modules.process_module import ProcessIO

if TYPE_CHECKING:
    from multiprocess_prototype.backend.shm.ring_buffer import RingBufferWriter


class CameraAdapter:
    """Реализует CameraOutputPort через ProcessIO (IPC) + RingBufferWriter (SHM).

    camera_id определяет SHM region/slot.
    ring_buffer обеспечивает безопасный round-robin fan-out.
    """

    def __init__(
        self,
        process,
        camera_id: int = 0,
        ring_buffer: RingBufferWriter | None = None,
    ) -> None:
        self._process = process
        self._io = ProcessIO(process)
        self._camera_id = camera_id
        self._ring_buffer = ring_buffer
        # Fallback SHM naming (если ring_buffer не задан)
        self._shm_region = f"camera_{camera_id}"
        self._shm_slot = f"camera_{camera_id}_frame"

    def send_frame_to_processor(self, data: dict) -> None:
        # camera_id в payload для маршрутизации
        # Target — конкретный процессор, привязанный к данной камере
        data_with_id = {**data, "camera_id": self._camera_id}
        self._io.send_data(f"processor_{self._camera_id}", "frame_ready", data_with_id)

    def send_to_gui(self, msg_type: str, data: dict) -> None:
        data_with_id = {**data, "camera_id": self._camera_id}
        self._io.send_data("gui", msg_type, data_with_id)

    def write_frame_to_shm(
        self, frame: np.ndarray, frame_id: int, timestamp: float
    ) -> dict | None:
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

    def request_shm_resize(self, new_width: int, new_height: int) -> None:
        """Запросить пересоздание SHM-региона под новое разрешение.

        Отправляет shm_region_change_request в process_manager.
        Camera продолжает работу (resize к старым размерам) до получения
        shm_region_changed ответа.
        """
        # Warning для больших регионов (>50MB per slot, 3 channels, uint8)
        region_bytes = new_width * new_height * 3
        if region_bytes > 50 * 1024 * 1024:
            self._process._log_warning(
                f"SHM region {self._shm_slot}: {new_width}x{new_height} = "
                f"{region_bytes / (1024 * 1024):.1f} MB per slot (>50MB)"
            )

        self._io.send_data(
            "process_manager",
            "shm_region_change_request",
            {
                "camera_id": self._camera_id,
                "region_name": f"camera_{self._camera_id}_frame",
                "new_width": new_width,
                "new_height": new_height,
            },
        )
