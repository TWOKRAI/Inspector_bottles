"""ProcessorAdapter — IPC/SHM facade для ProcessorService.

Task 2.4: каждый Processor привязан к камере через camera_id.
Маска пишется в processor_{camera_id}_mask, feedback идёт в camera_{camera_id}.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module import ProcessIO


class ProcessorAdapter:
    """Реализует ProcessorOutputPort через ProcessIO (IPC + SHM facade).

    camera_id определяет SHM-слот маски и target для feedback.
    """

    def __init__(self, process, camera_id: int = 0) -> None:
        self._io = ProcessIO(process)
        self._camera_id = camera_id

    def send_detection_to_renderer(self, result_data: dict) -> None:
        # Все процессоры шлют в единый renderer
        self._io.send_data("renderer", "detection_result", result_data)

    def send_detections_to_database(self, rows: list[dict]) -> None:
        self._io.send_command("database", "db.save_detections", args={"detections": rows})

    def send_feedback_to_camera(self, frame_id: int, processing_time: float) -> None:
        self._io.send_event(
            f"camera_{self._camera_id}",
            "frame_processed",
            {"frame_id": frame_id, "processing_time": processing_time},
        )

    def write_mask_to_shm(self, mask) -> tuple[str | None, int]:
        """Записать маску в SHM через ProcessIO. Возвращает tuple (name, index).

        SHM-слот привязан к camera_id: processor_{camera_id}_mask.
        """
        mask_slot = f"processor_{self._camera_id}_mask"
        result = self._io.write_frames_to_shm(self._io._p.name, mask_slot, [mask])
        if result is None:
            return None, 0
        return result.get("shm_actual_name"), result.get("shm_index", 0)
