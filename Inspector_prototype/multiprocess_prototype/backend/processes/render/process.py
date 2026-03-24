# multiprocess_prototype/backend/processes/render/process.py
"""
RendererProcess — отрисовка bbox и контуров на кадрах.

Домен: `backend.modules.renderer` (drawing, frame_io, register_sync).
"""

import time

from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.message_module import MessageAdapter
from multiprocess_framework.modules.worker_module import (
    ThreadConfig,
    ExecutionMode,
)
from multiprocess_prototype.backend.modules.renderer.drawing import (
    RenderOverlayState,
    apply_detection_overlays,
)
from multiprocess_prototype.backend.modules.renderer.frame_io import (
    read_frames_from_detection_result,
)
from multiprocess_prototype.backend.modules.renderer.register_sync import (
    apply_renderer_register_update,
)
from multiprocess_prototype.backend.shared import message_as_dict


class RendererProcess(ProcessModule):
    """Процесс отрисовки. Owner rendered_frame, consumer camera_frame."""

    def _init_application_threads(self):
        self._log_info("RendererProcess initializing...")

        self._msg = MessageAdapter(sender=self.name)

        self._output_dir = self.get_config("output_dir", "./output_frames")
        self._save_frames = self.get_config("save_frames", False)
        self._draw_bboxes = self.get_config("draw_bboxes", True)
        self._overlay_state = RenderOverlayState(
            draw_contours=self.get_config("draw_contours", True),
        )
        self._show_original = self.get_config("show_original", True)
        self._show_mask = self.get_config("show_mask", True)

        self.command_manager.register_command("set_draw_contours", self._cmd_set_draw_contours)
        self.command_manager.register_command("set_show_original", self._cmd_set_show_original)
        self.command_manager.register_command("set_show_mask", self._cmd_set_show_mask)
        self.command_manager.register_command("set_draw_bboxes", self._cmd_set_draw_bboxes)
        self.command_manager.register_command("set_save_frames", self._cmd_set_save_frames)

        if not self.memory_manager:
            self._log_warning("MemoryManager not available, shared memory disabled")

        config = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker(
            "render_worker", self._render_worker, config, auto_start=True
        )

        self._log_info("RendererProcess ready")

    def _render_worker(self, stop_event, pause_event):
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            msg = self.receive_message(timeout=0.1, channel_types=["data"])
            msg_dict = message_as_dict(msg)
            if msg_dict.get("data_type") == "register_update":
                apply_renderer_register_update(
                    msg_dict.get("data") or {},
                    set_draw_contours=self._cmd_set_draw_contours,
                    set_show_original=self._cmd_set_show_original,
                    set_show_mask=self._cmd_set_show_mask,
                    set_draw_bboxes=self._cmd_set_draw_bboxes,
                    set_save_frames=self._cmd_set_save_frames,
                )
                continue

            frame, mask_frame, data = read_frames_from_detection_result(
                msg,
                self.memory_manager,
                log_info=self._log_info,
                log_warning=self._log_warning,
            )
            if frame is None:
                continue

            overlay = RenderOverlayState(
                draw_bboxes=self._draw_bboxes,
                draw_contours=self._overlay_state.draw_contours,
            )
            frame = apply_detection_overlays(
                frame,
                data,
                overlay,
                output_dir=self._output_dir,
                save_frames=self._save_frames,
            )
            self._write_and_notify(frame, mask_frame, data)
            self._send_robot_and_camera_feedback(
                data.get("frame_id", 0), data.get("detections", [])
            )

            self._record_metric("renderer.frames_rendered", value=1)
            self._record_metric(
                "renderer.detections_per_frame", value=len(data.get("detections", []))
            )

    def _write_and_notify(self, frame, mask_frame, data: dict):
        mm = self.memory_manager
        if not mm:
            return
        width = data.get("width", 640)
        height = data.get("height", 480)
        frame_id = data.get("frame_id", 0)
        detections = data.get("detections", [])
        free_idx_rendered = mm.find_free_index("renderer", "rendered_frame") or 0
        shm_rendered_name = mm.write_images(
            "renderer", "rendered_frame", [frame], free_idx_rendered
        )
        free_idx_mask = mm.find_free_index("renderer", "mask_frame") or 0
        shm_mask_name = mm.write_images("renderer", "mask_frame", [mask_frame], free_idx_mask)
        if shm_rendered_name:
            if frame_id <= 3 or frame_id % 50 == 0:
                self._log_info(
                    f"[DEBUG] renderer: sending rendered_frame_ready to gui frame_id={frame_id}"
                )
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
                "draw_contours": self._overlay_state.draw_contours,
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
        val = data.get("draw_contours", self._overlay_state.draw_contours)
        self._overlay_state.draw_contours = bool(val)
        self._log_info(f"Draw contours set to {self._overlay_state.draw_contours}")
        return {"status": "ok", "draw_contours": self._overlay_state.draw_contours}

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

    def _cmd_set_draw_bboxes(self, data):
        val = data.get("draw_bboxes", self._draw_bboxes)
        self._draw_bboxes = bool(val)
        return {"status": "ok", "draw_bboxes": self._draw_bboxes}

    def _cmd_set_save_frames(self, data):
        val = data.get("save_frames", self._save_frames)
        self._save_frames = bool(val)
        return {"status": "ok", "save_frames": self._save_frames}

    def shutdown(self) -> bool:
        self._log_info("RendererProcess shutting down...")
        if self.memory_manager:
            self.memory_manager.close_all("renderer")
        self.is_initialized = False
        return super().shutdown()
