# multiprocess_prototype_v3/backend/processes/camera_sim/process.py
"""Синтетические кадры → SharedMemory + уведомление processor."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import numpy as np

from multiprocess_framework.modules.message_module import MessageAdapter
from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig


class CameraSimProcess(ProcessModule):
    """Пишет кадр в SHM `camera_frame` и шлёт лёгкое DATA-сообщение."""

    def _init_application_threads(self) -> None:
        self.msg = MessageAdapter(sender=self.name)
        self._fps = int(self.get_config("fps", 10))
        self._frame_id = 0
        self._frame_color = str(self.get_config("frame_color", "noise"))
        self._height = int(self.get_config("resolution_height", 480))
        self._width = int(self.get_config("resolution_width", 640))

        self.command_manager.register_command("register_update", self._apply_register_update)

        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker("capture", self._capture_loop, cfg, auto_start=True)

    def _apply_register_update(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(data, dict):
            return {"status": "error", "reason": "invalid payload"}
        field = data.get("field_name") or data.get("field")
        value = data.get("value")
        if field == "fps":
            self._fps = max(1, int(value))
            self.update_config("fps", self._fps)
        elif field == "frame_color":
            self._frame_color = str(value)
            self.update_config("frame_color", self._frame_color)
        elif field == "resolution_height":
            self._height = max(1, int(value))
            self.update_config("resolution_height", self._height)
            self._log_warning(
                "resolution change may mismatch SHM layout until full restart"
            )
        elif field == "resolution_width":
            self._width = max(1, int(value))
            self.update_config("resolution_width", self._width)
            self._log_warning(
                "resolution change may mismatch SHM layout until full restart"
            )
        return {"status": "ok", "field": field}

    def _make_frame(self) -> np.ndarray:
        if self._frame_color == "dark":
            return np.zeros((self._height, self._width, 3), dtype=np.uint8)
        if self._frame_color == "bright":
            return np.full((self._height, self._width, 3), 255, dtype=np.uint8)
        return np.random.default_rng().integers(
            0, 256, size=(self._height, self._width, 3), dtype=np.uint8
        )

    def _capture_loop(self, stop_event, pause_event) -> None:
        mm = self.memory_manager
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue
            if not mm:
                time.sleep(0.2)
                continue
            interval = 1.0 / max(1, self._fps)
            frame = self._make_frame()
            idx = mm.find_free_index(self.name, "camera_frame")
            if idx is None:
                idx = 0
            mm.write_images(self.name, "camera_frame", [frame], idx)
            self._frame_id += 1
            note = self.msg.data(
                targets=["processor"],
                data_type="frame",
                data={"shm_index": idx, "frame_id": self._frame_id},
            )
            self.send_message("processor", note.to_dict())
            self._log_info(f"Frame {self._frame_id} → slot {idx}")
            stop_event.wait(interval)
