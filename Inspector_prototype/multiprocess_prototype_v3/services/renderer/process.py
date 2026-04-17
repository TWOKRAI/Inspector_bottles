"""RendererProcess — draws bboxes and contours on frames."""

import time

from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.message_module import MessageAdapter
from multiprocess_framework.modules.worker_module import ThreadConfig, ExecutionMode

from multiprocess_prototype_v3.registers import RENDERER_REGISTER
from multiprocess_prototype_v3.services.renderer.drawing import RenderOverlayState, apply_detection_overlays
from multiprocess_prototype_v3.shared.frame_io import read_frame_from_msg, read_frame_from_shm, message_as_dict
from multiprocess_prototype_v3.shared.register_sync import apply_register_update

try:
    import cv2
except ImportError:
    cv2 = None

import numpy as np


class RendererProcess(ProcessModule):
    """Rendering process. Owner of rendered_frame, consumer of camera_frame."""

    def _init_application_threads(self):
        self._log_info("RendererProcess initializing...")
        self._msg = MessageAdapter(sender=self.name)
        self._output_dir = self.get_config("output_dir", "./output_frames")
        self._save_frames = self.get_config("save_frames", False)
        self._draw_bboxes = self.get_config("draw_bboxes", True)
        self._overlay_state = RenderOverlayState(draw_contours=self.get_config("draw_contours", True))
        self._show_original = self.get_config("show_original", True)
        self._show_mask = self.get_config("show_mask", True)

        for cmd, handler in {
            "set_draw_contours": self._cmd_set_draw_contours,
            "set_show_original": self._cmd_set_show_original,
            "set_show_mask": self._cmd_set_show_mask,
            "set_draw_bboxes": self._cmd_set_draw_bboxes,
            "set_save_frames": self._cmd_set_save_frames,
        }.items():
            self.command_manager.register_command(cmd, handler)

        config = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker("render_worker", self._render_worker, config, auto_start=True)
        self._log_info("RendererProcess ready")

    def _build_register_handlers(self) -> dict:
        return {
            "show_original": lambda v: self._cmd_set_show_original({"show_original": v}),
            "show_mask": lambda v: self._cmd_set_show_mask({"show_mask": v}),
            "draw_contours": lambda v: self._cmd_set_draw_contours({"draw_contours": v}),
            "draw_bboxes": lambda v: self._cmd_set_draw_bboxes({"draw_bboxes": v}),
            "save_frames": lambda v: self._cmd_set_save_frames({"save_frames": v}),
        }

    def _render_worker(self, stop_event, pause_event):
        register_handlers = self._build_register_handlers()
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            msg = self.receive_message(timeout=0.1, channel_types=["data"])
            msg_dict = message_as_dict(msg)
            if msg_dict.get("data_type") == "register_update":
                apply_register_update(msg_dict.get("data") or {}, RENDERER_REGISTER, register_handlers)
                continue

            if msg_dict.get("data_type") != "detection_result":
                continue
            data = msg_dict.get("data", {})

            # Read original frame from camera SHM
            mm = self.memory_manager
            frame = None
            if mm:
                images = mm.read_images("camera", "camera_frame", data.get("shm_index", 0), n=1)
                if images:
                    frame = images[0].copy()
            if frame is None and data.get("shm_actual_name"):
                frame = read_frame_from_shm(data["shm_actual_name"], data.get("width", 640), data.get("height", 480))
                if frame is not None:
                    frame = frame.copy()
            if frame is None:
                continue

            width, height = data.get("width", 640), data.get("height", 480)
            if (frame.shape[0] != height or frame.shape[1] != width) and cv2 is not None:
                frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_LINEAR)

            # Read mask from processor SHM
            mask_frame = None
            if mm and data.get("mask_shm_actual_name"):
                images = mm.read_images("processor", "processor_mask", data.get("mask_shm_index", 0), n=1)
                if images:
                    mask_frame = images[0].copy()
            if mask_frame is None and data.get("mask_shm_actual_name"):
                mask_frame = read_frame_from_shm(data["mask_shm_actual_name"], width, height)
                if mask_frame is not None:
                    mask_frame = mask_frame.copy()
            if mask_frame is None:
                mask_frame = np.zeros((height, width, 3), dtype=np.uint8)

            overlay = RenderOverlayState(draw_bboxes=self._draw_bboxes, draw_contours=self._overlay_state.draw_contours)
            frame = apply_detection_overlays(frame, data, overlay, output_dir=self._output_dir, save_frames=self._save_frames)
            self._write_and_notify(frame, mask_frame, data)

            detections = data.get("detections", [])
            if detections:
                robot_cmd = self._msg.command(targets=["robot"], command="reject_item",
                                               args={"frame_id": data.get("frame_id", 0), "defects": detections},
                                               data={"frame_id": data.get("frame_id", 0), "defects": detections})
                self.send_message("robot", robot_cmd.to_dict())

    def _write_and_notify(self, frame, mask_frame, data: dict):
        mm = self.memory_manager
        if not mm:
            return
        width, height = data.get("width", 640), data.get("height", 480)
        frame_id = data.get("frame_id", 0)
        detections = data.get("detections", [])

        free_idx_rendered = mm.find_free_index("renderer", "rendered_frame") or 0
        shm_rendered_name = mm.write_images("renderer", "rendered_frame", [frame], free_idx_rendered)
        free_idx_mask = mm.find_free_index("renderer", "mask_frame") or 0
        shm_mask_name = mm.write_images("renderer", "mask_frame", [mask_frame], free_idx_mask)

        if shm_rendered_name:
            notif_data = {
                "frame_id": frame_id, "shm_name": "rendered_frame",
                "shm_index": free_idx_rendered, "shm_actual_name": shm_rendered_name,
                "width": width, "height": height,
                "detections_count": len(detections),
                "show_original": self._show_original, "show_mask": self._show_mask,
                "draw_contours": self._overlay_state.draw_contours,
            }
            if shm_mask_name:
                notif_data["mask_shm_name"] = "mask_frame"
                notif_data["mask_shm_index"] = free_idx_mask
                notif_data["mask_shm_actual_name"] = shm_mask_name
            gui_msg = self._msg.data(targets=["gui"], data_type="rendered_frame_ready", data=notif_data)
            self.send_message("gui", gui_msg.to_dict())

    def _cmd_set_draw_contours(self, data):
        self._overlay_state.draw_contours = bool(data.get("draw_contours", self._overlay_state.draw_contours))
        return {"status": "ok"}

    def _cmd_set_show_original(self, data):
        self._show_original = bool(data.get("show_original", self._show_original))
        return {"status": "ok"}

    def _cmd_set_show_mask(self, data):
        self._show_mask = bool(data.get("show_mask", self._show_mask))
        return {"status": "ok"}

    def _cmd_set_draw_bboxes(self, data):
        self._draw_bboxes = bool(data.get("draw_bboxes", self._draw_bboxes))
        return {"status": "ok"}

    def _cmd_set_save_frames(self, data):
        self._save_frames = bool(data.get("save_frames", self._save_frames))
        return {"status": "ok"}

    def shutdown(self) -> bool:
        self._log_info("RendererProcess shutting down...")
        if self.memory_manager:
            self.memory_manager.close_all("renderer")
        self.is_initialized = False
        return super().shutdown()
