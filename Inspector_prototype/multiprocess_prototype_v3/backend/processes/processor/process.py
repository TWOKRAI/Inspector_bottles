# multiprocess_prototype_v3/backend/processes/processor/process.py
"""Чтение кадра из SHM camera_sim → яркость → результат aggregator."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import numpy as np

from multiprocess_framework.modules.message_module import MessageAdapter
from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig


class ProcessorProcess(ProcessModule):
    """Анализ кадра в разделяемой памяти процесса camera_sim."""

    def _init_application_threads(self) -> None:
        self.msg = MessageAdapter(sender=self.name)
        self._threshold = int(self.get_config("brightness_threshold", 128))
        self._enabled = bool(self.get_config("enabled", True))

        self.command_manager.register_command("register_update", self._apply_register_update)

        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker("process", self._process_loop, cfg, auto_start=True)

    def _apply_register_update(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(data, dict):
            return {"status": "error", "reason": "invalid payload"}
        field = data.get("field_name") or data.get("field")
        value = data.get("value")
        if field == "brightness_threshold":
            self._threshold = int(value)
            self.update_config("brightness_threshold", self._threshold)
        elif field == "enabled":
            self._enabled = bool(value)
            self.update_config("enabled", self._enabled)
        return {"status": "ok", "field": field}

    def _process_loop(self, stop_event, pause_event) -> None:
        mm = self.memory_manager
        while not stop_event.is_set():
            if pause_event.is_set() or not self._enabled:
                time.sleep(0.05)
                continue
            msgs = self.receive(timeout=0.15, channel_types=["data"])
            for msg in msgs:
                if not isinstance(msg, dict):
                    continue
                if msg.get("data_type") != "frame":
                    continue
                body = msg.get("data") or {}
                if not isinstance(body, dict):
                    continue
                idx = int(body.get("shm_index", 0))
                frame_id = int(body.get("frame_id", 0))
                if not mm:
                    continue
                imgs = mm.read_images("camera_sim", "camera_frame", idx, n=1, copy=True)
                if not imgs:
                    continue
                arr = imgs[0]
                brightness = float(np.mean(arr))
                is_defect = brightness < self._threshold
                out = self.msg.data(
                    targets=["aggregator"],
                    data_type="inspection_result",
                    data={
                        "frame_id": frame_id,
                        "brightness": brightness,
                        "is_defect": is_defect,
                        "threshold": self._threshold,
                    },
                )
                self.send_message("aggregator", out.to_dict())
                self._log_info(
                    f"frame={frame_id} mean={brightness:.1f} defect={is_defect}"
                )
            time.sleep(0.01)
