"""ProcessorAdapter — IPC/SHM facade для ProcessorService."""
from __future__ import annotations

from typing import Optional

from multiprocess_framework.modules.process_module import ProcessIO


class ProcessorAdapter:
    """Реализует ProcessorOutputPort через ProcessIO (IPC + SHM facade)."""

    def __init__(self, process) -> None:
        self._io = ProcessIO(process)

    def send_detection_to_renderer(self, result_data: dict) -> None:
        self._io.send_data("renderer", "detection_result", result_data)

    def send_detections_to_database(self, rows: list[dict]) -> None:
        self._io.send_command(
            "database", "db.save_detections", args={"detections": rows}
        )

    def send_feedback_to_camera(self, frame_id: int, processing_time: float) -> None:
        self._io.send_event(
            "camera",
            "frame_processed",
            {"frame_id": frame_id, "processing_time": processing_time},
        )

    def write_mask_to_shm(self, mask) -> tuple[Optional[str], int]:
        """Записать маску в SHM через ProcessIO. Возвращает tuple (name, index)."""
        result = self._io.write_frames_to_shm(self._io._p.name, "processor_mask", [mask])
        if result is None:
            return None, 0
        return result.get("shm_actual_name"), result.get("shm_index", 0)
