"""
RendererProcess — отрисовка bbox и контуров на кадрах.

Consumer camera_frame, processor_mask (чтение через shm из detection_result).
Owner rendered_frame, mask_frame (запись для GUI).
Отправляет DATA rendered_frame_ready в GUI, COMMAND reject_item в Robot,
EVENT frame_rendered в Camera.
"""

import os
import time

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

from multiprocess_framework.refactored.modules.process_module import ProcessModule
from multiprocess_framework.refactored.modules.message_module import MessageAdapter
from multiprocess_framework.refactored.modules.worker_module import (
    ThreadConfig,
    ExecutionMode,
)
from multiprocess_prototype.utils.shm_utils import read_frame_from_shm


def _draw_bbox(frame: np.ndarray, bbox: list, color: tuple = (0, 255, 0), thickness: int = 2):
    """Отрисовать bbox на кадре (numpy, без OpenCV)."""
    x1, y1, x2, y2 = bbox
    h, w = frame.shape[:2]
    x1, x2 = max(0, x1), min(w, x2)
    y1, y2 = max(0, y1), min(h, y2)
    t = min(thickness, x2 - x1, y2 - y1)
    if t <= 0:
        return
    frame[y1 : y1 + t, x1:x2, :] = color
    frame[y2 - t : y2, x1:x2, :] = color
    frame[y1:y2, x1 : x1 + t, :] = color
    frame[y1:y2, x2 - t : x2, :] = color


class RendererProcess(ProcessModule):
    """Процесс отрисовки. Owner rendered_frame, consumer camera_frame."""

    def _init_application_threads(self):
        """Инициализация RendererProcess: SharedMemory, воркер render_worker."""
        self._log_info("RendererProcess initializing...")

        self._msg = MessageAdapter(sender=self.name)

        self._output_dir = self.get_config("output_dir", "./output_frames")
        self._save_frames = self.get_config("save_frames", False)
        self._draw_bboxes = self.get_config("draw_bboxes", True)
        self._draw_contours = self.get_config("draw_contours", True)
        self._show_original = self.get_config("show_original", True)
        self._show_mask = self.get_config("show_mask", True)

        # Команды отображения от GUI
        self.command_manager.register_command("set_draw_contours", self._cmd_set_draw_contours)
        self.command_manager.register_command("set_show_original", self._cmd_set_show_original)
        self.command_manager.register_command("set_show_mask", self._cmd_set_show_mask)

        # Shared Memory: создаётся фреймворком из config["memory"] в process_runner
        if not self.memory_manager:
            self._log_warning("MemoryManager not available, shared memory disabled")

        config = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker(
            "render_worker", self._render_worker, config, auto_start=True
        )

        self._log_info("RendererProcess ready")

    def _render_worker(self, stop_event, pause_event):
        """Циклическая отрисовка. Режим LOOP."""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            msg = self.receive_message(timeout=0.1, channel_types=['data'])
            frame, mask_frame, data = self._read_input_frames(msg)
            if frame is None:
                continue

            frame = self._prepare_output_frames(frame, mask_frame, data)
            self._write_and_notify(frame, mask_frame, data)
            self._send_robot_and_camera_feedback(data.get("frame_id", 0), data.get("detections", []))

            self._record_metric("renderer.frames_rendered", value=1)
            self._record_metric("renderer.detections_per_frame", value=len(data.get("detections", [])))

    def _read_input_frames(self, msg) -> tuple:
        """Чтение original и mask из shm. Возврат (frame, mask_frame, data) или (None, None, {})."""
        if msg is None:
            return None, None, {}
        msg_dict = msg if isinstance(msg, dict) else (msg.to_dict() if hasattr(msg, "to_dict") else {})
        if msg_dict.get("data_type") != "detection_result":
            return None, None, {}
        data = msg_dict.get("data", {})
        frame_id = data.get("frame_id", 0)
        if frame_id <= 3 or frame_id % 50 == 0:
            self._log_info(f"[DEBUG] renderer: detection_result received frame_id={frame_id}")
        shm_index = data.get("shm_index", 0)
        width = data.get("width", 640)
        height = data.get("height", 480)
        shm_actual_name = data.get("shm_actual_name")
        mask_shm_index = data.get("mask_shm_index", 0)
        mask_shm_actual_name = data.get("mask_shm_actual_name")
        mm = self.memory_manager

        frame = None
        if mm:
            images = mm.read_images("camera", "camera_frame", shm_index, n=1)
            if images:
                frame = images[0].copy()
        if frame is None and shm_actual_name:
            frame = read_frame_from_shm(shm_actual_name, width, height)
            if frame is not None:
                frame = frame.copy()
        if frame is None:
            self._log_warning(f"[DEBUG] renderer: frame is None for frame_id={frame_id}")
            return None, None, {}

        mask_frame = None
        if mm and mask_shm_actual_name:
            images = mm.read_images("processor", "processor_mask", mask_shm_index, n=1)
            if images:
                mask_frame = images[0].copy()
        if mask_frame is None and mask_shm_actual_name:
            mask_frame = read_frame_from_shm(mask_shm_actual_name, width, height)
            if mask_frame is not None:
                mask_frame = mask_frame.copy()
        if mask_frame is None:
            mask_frame = np.zeros((height, width, 3), dtype=np.uint8)

        return frame, mask_frame, data

    def _prepare_output_frames(self, frame: np.ndarray, mask_frame: np.ndarray, data: dict) -> np.ndarray:
        """Отрисовка bbox и контуров на оригинале. Возврат frame (модифицированный)."""
        detections = data.get("detections", [])
        contours = data.get("contours", [])
        frame_id = data.get("frame_id", 0)
        if self._draw_bboxes:
            for det in detections:
                _draw_bbox(frame, det.get("bbox", [0, 0, 0, 0]))
        if self._draw_contours and contours and cv2 is not None:
            cv2.drawContours(frame, contours, -1, (0, 255, 0), 2)
        if self._save_frames:
            os.makedirs(self._output_dir, exist_ok=True)
            np.save(os.path.join(self._output_dir, f"frame_{frame_id:06d}.npy"), frame)
        return frame

    def _write_and_notify(self, frame: np.ndarray, mask_frame: np.ndarray, data: dict):
        """Запись в shm и отправка gui_notification."""
        mm = self.memory_manager
        if not mm:
            return
        width = data.get("width", 640)
        height = data.get("height", 480)
        frame_id = data.get("frame_id", 0)
        detections = data.get("detections", [])
        free_idx_rendered = mm.find_free_index("renderer", "rendered_frame") or 0
        shm_rendered_name = mm.write_images("renderer", "rendered_frame", [frame], free_idx_rendered)
        free_idx_mask = mm.find_free_index("renderer", "mask_frame") or 0
        shm_mask_name = mm.write_images("renderer", "mask_frame", [mask_frame], free_idx_mask)
        if shm_rendered_name:
            if frame_id <= 3 or frame_id % 50 == 0:
                self._log_info(f"[DEBUG] renderer: sending rendered_frame_ready to gui frame_id={frame_id}")
            notif_data = {
                "frame_id": frame_id,
                "shm_name": "rendered_frame",
                "shm_index": free_idx_rendered,
                "shm_actual_name": shm_rendered_name,
                "width": width,
                "height": height,
                "detections_count": len(detections),
                "show_original": self._show_original,
                "show_mask": self._show_mask,
                "draw_contours": self._draw_contours,
            }
            if shm_mask_name:
                notif_data["mask_shm_name"] = "mask_frame"
                notif_data["mask_shm_index"] = free_idx_mask
                notif_data["mask_shm_actual_name"] = shm_mask_name
            gui_notification = self._msg.data(
                targets=["gui"],
                data_type="rendered_frame_ready",
                data=notif_data,
            )
            self.send_message("gui", gui_notification.to_dict())

    def _send_robot_and_camera_feedback(self, frame_id: int, detections: list):
        """Отправка reject_item в Robot и frame_rendered в Camera."""
        if detections:
            robot_cmd = self._msg.command(
                targets=["robot"],
                command="reject_item",
                args={"frame_id": frame_id, "defects": detections},
                data={"frame_id": frame_id, "defects": detections},
            )
            self.send_message("robot", robot_cmd.to_dict())
        feedback = self._msg.event(
            event_type="frame_rendered",
            targets=["camera"],
            event_data={"frame_id": frame_id},
        )
        self.send_message("camera", feedback.to_dict())

    def _cmd_set_draw_contours(self, data):
        val = data.get("draw_contours", self._draw_contours)
        self._draw_contours = bool(val)
        self._log_info(f"Draw contours set to {self._draw_contours}")
        return {"status": "ok", "draw_contours": self._draw_contours}

    def _cmd_set_show_original(self, data):
        val = data.get("show_original", self._show_original)
        self._show_original = bool(val)
        self._log_info(f"Show original set to {self._show_original}")
        return {"status": "ok", "show_original": self._show_original}

    def _cmd_set_show_mask(self, data):
        val = data.get("show_mask", self._show_mask)
        self._show_mask = bool(val)
        self._log_info(f"Show mask set to {self._show_mask}")
        return {"status": "ok", "show_mask": self._show_mask}

    def shutdown(self) -> bool:
        self._log_info("RendererProcess shutting down...")
        if self.memory_manager:
            self.memory_manager.close_all("renderer")
        self.is_initialized = False
        return super().shutdown()
