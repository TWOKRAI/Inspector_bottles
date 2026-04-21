"""RendererAdapter — IPC/SHM facade для RendererService."""
from __future__ import annotations

from typing import Optional

import numpy as np

from multiprocess_framework.modules.process_module import ProcessIO


class RendererAdapter:
    """Реализует RendererOutputPort через ProcessIO (IPC + SHM facade)."""

    def __init__(self, process) -> None:
        self._io = ProcessIO(process)

    def send_rendered_to_gui(self, notification_data: dict) -> None:
        self._io.send_data("gui", "rendered_frame_ready", notification_data)

    def send_reject_to_robot(self, frame_id: int, defects: list[dict]) -> None:
        payload = {"frame_id": frame_id, "defects": defects}
        self._io.send_command("robot", "reject_item", args=payload, data=payload)

    def write_rendered_to_shm(self, frame: np.ndarray, mask: np.ndarray) -> Optional[dict]:
        """Записать rendered frame и mask в SHM (два отдельных слота)."""
        rendered = self._io.write_frames_to_shm("renderer", "rendered_frame", [frame])
        if rendered is None:
            return None
        mask_info = self._io.write_frames_to_shm("renderer", "mask_frame", [mask])
        if mask_info is not None:
            rendered["mask_shm_name"] = mask_info["shm_name"]
            rendered["mask_shm_index"] = mask_info["shm_index"]
            rendered["mask_shm_actual_name"] = mask_info["shm_actual_name"]
        return rendered
