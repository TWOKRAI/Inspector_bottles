"""GuiProcess — PyQt5 GUI process."""

from multiprocess_framework.modules.message_module import MessageAdapter
from multiprocess_framework.modules.process_module import ProcessModule

from multiprocess_prototype_v3.shared.frame_io import read_frame_from_shm

import numpy as np
from typing import Any, Dict, List, Optional

from frontend_module.core.routed_command import RoutedCommandSender


# --- Command routing ---
COMMAND_TO_REGISTER_KEY: Dict[str, str] = {
    "start_capture": "camera", "stop_capture": "camera", "set_fps": "camera",
    "set_color_range": "processor", "set_min_area": "processor", "set_max_area": "processor",
    "set_show_original": "renderer", "set_show_mask": "renderer",
    "set_draw_contours": "renderer", "set_draw_bboxes": "renderer", "set_save_frames": "renderer",
    "enum_devices": "camera", "open": "camera", "close": "camera",
    "start_grabbing": "camera", "stop_grabbing": "camera",
    "get_parameters": "camera", "set_parameters": "camera", "set_camera_type": "camera",
}
EXPLICIT_COMMAND_TARGETS: Dict[str, List[str]] = {"system.shutdown": ["ProcessManager"]}


def resolve_command_targets(command_id: str) -> List[str]:
    if command_id in EXPLICIT_COMMAND_TARGETS:
        return list(EXPLICIT_COMMAND_TARGETS[command_id])
    return [COMMAND_TO_REGISTER_KEY[command_id]]


class GuiProcess(ProcessModule):
    """GUI process: FrontendManager, WindowManager, RegistersManager."""

    def _init_application_threads(self):
        self._log_info("GuiProcess initializing...")
        self._msg = MessageAdapter(sender=self.name)
        self._routed_command_sender = RoutedCommandSender(
            router=self, message_factory=self._msg,
            resolve_targets=resolve_command_targets,
            get_args_builder=lambda cid: None,
        )
        app_cfg = self.get_config("config") or {}
        self._poll_interval = app_cfg.get("poll_interval_ms", 16)
        self._window_title = app_cfg.get("window_title", "Inspector Prototype")
        self._camera_type = app_cfg.get("camera_type", "simulator")
        self._window = None
        self._gui_msg_count = 0
        self._log_info("GuiProcess ready")

    def _init_system_threads(self):
        pass

    def _stop_system_threads(self):
        pass

    def run(self):
        from multiprocess_prototype_v3.frontend.launcher import FrontendLauncher
        app_cfg = self.get_config("config") or {}
        launcher = FrontendLauncher(process_ref=self, app_config=app_cfg)
        launcher.run(initial_window="loading", loading_delay_ms=2000)

    # --- Command sender ---
    def _send_command(self, command_id: str, args=None, data=None) -> bool:
        return self._routed_command_sender.send(command_id, args=args or {}, data=data)

    # --- Message polling (called by QTimer) ---
    def _poll_messages(self):
        msgs = self.receive(timeout=0.001, channel_types=["data"])
        for msg in msgs:
            msg_dict = msg if isinstance(msg, dict) else (msg.to_dict() if hasattr(msg, "to_dict") else {})
            data_type = msg_dict.get("data_type")
            data = msg_dict.get("data", {})
            if data_type == "rendered_frame_ready":
                self._handle_new_frame(data)
            elif data_type == "status":
                self._handle_camera_status(data.get("status", ""))
            elif data_type == "error":
                self._handle_camera_error(data.get("error", ""))
            elif data_type == "parameters_response":
                self._handle_parameters_response(data)
            elif data_type == "enum_devices_response":
                self._handle_enum_devices_response(data)
            elif data_type == "camera_type_changed":
                self._handle_camera_type_changed(data)
            elif data_type == "fps_update":
                self._handle_fps_update(data)

    # --- Handlers ---
    def _handle_camera_status(self, text):
        if self._window and hasattr(self._window, "update_camera_status"):
            self._window.update_camera_status(text)

    def _handle_camera_error(self, text):
        self._log_error(f"Camera error: {text}")
        if self._window and hasattr(self._window, "update_camera_error"):
            self._window.update_camera_error(text)

    def _handle_parameters_response(self, data):
        if self._window and hasattr(self._window, "update_camera_parameters"):
            self._window.update_camera_parameters(data.get("parameters", {}))

    def _handle_enum_devices_response(self, data):
        if self._window and hasattr(self._window, "update_camera_devices"):
            self._window.update_camera_devices(data.get("devices", []))

    def _handle_camera_type_changed(self, data):
        if self._window and hasattr(self._window, "sync_camera_type"):
            self._window.sync_camera_type(data.get("camera_type", "simulator"))

    def _handle_fps_update(self, data):
        if self._window and hasattr(self._window, "update_camera_fps"):
            self._window.update_camera_fps(data.get("fps", 0))

    def _handle_new_frame(self, data):
        mm = self.memory_manager
        shm_index = data.get("shm_index", 0)
        width, height = data.get("width", 640), data.get("height", 480)

        original_frame = None
        if mm:
            images = mm.read_images("renderer", "rendered_frame", shm_index, n=1)
            if images:
                original_frame = images[0]
        if original_frame is None and data.get("shm_actual_name"):
            original_frame = read_frame_from_shm(data["shm_actual_name"], width, height)

        mask_frame = None
        if mm and data.get("mask_shm_actual_name"):
            mask_images = mm.read_images("renderer", "mask_frame", data.get("mask_shm_index", 0), n=1)
            if mask_images:
                mask_frame = mask_images[0]
        if mask_frame is None and data.get("mask_shm_actual_name"):
            mask_frame = read_frame_from_shm(data["mask_shm_actual_name"], width, height)

        if self._window:
            self._window.update_frame(
                original_frame if original_frame is not None else np.zeros((height, width, 3), dtype=np.uint8),
                mask_frame if mask_frame is not None else np.zeros((height, width, 3), dtype=np.uint8),
                data.get("frame_id", 0),
                show_original=data.get("show_original", True),
                show_mask=data.get("show_mask", True),
            )

    def _check_stop(self, app):
        if self.should_stop():
            app.quit()

    # --- GUI API ---
    def gui_request_shutdown(self):
        try:
            self._send_command("system.shutdown", {}, {})
        except Exception as e:
            self._log_error(f"GUI: failed to send shutdown: {e}")

    def gui_start_capture(self):
        self._send_command("start_capture", {}, {})

    def gui_stop_capture(self):
        self._send_command("stop_capture", {}, {})

    def gui_set_fps(self, fps):
        self._send_command("set_fps", {"fps": fps}, {"fps": fps})

    def gui_set_color_range(self, b_lower, g_lower, r_lower, b_upper, g_upper, r_upper):
        self._send_command("set_color_range", {}, {
            "color_lower": [b_lower, g_lower, r_lower],
            "color_upper": [b_upper, g_upper, r_upper],
        })

    def gui_set_min_area(self, min_area):
        self._send_command("set_min_area", {"min_area": min_area}, {"min_area": min_area})

    def gui_set_max_area(self, max_area):
        self._send_command("set_max_area", {"max_area": max_area}, {"max_area": max_area})

    def gui_set_show_original(self, show):
        self._send_command("set_show_original", {"show_original": show}, {"show_original": show})

    def gui_set_show_mask(self, show):
        self._send_command("set_show_mask", {"show_mask": show}, {"show_mask": show})

    def gui_set_draw_contours(self, draw):
        self._send_command("set_draw_contours", {"draw_contours": draw}, {"draw_contours": draw})

    def gui_enum_devices(self):
        self._send_command("enum_devices", {}, {})

    def gui_open_camera(self, camera_index=0):
        self._send_command("open", {"camera_index": camera_index}, {"camera_index": camera_index})

    def gui_close_camera(self):
        self._send_command("close", {}, {})

    def gui_start_grabbing(self):
        self._send_command("start_grabbing", {}, {})

    def gui_stop_grabbing(self):
        self._send_command("stop_grabbing", {}, {})

    def gui_get_parameters(self):
        self._send_command("get_parameters", {}, {})

    def gui_set_parameters(self, frame_rate, exposure_time, gain):
        self._send_command("set_parameters", {}, {
            "frame_rate": frame_rate, "exposure_time": exposure_time, "gain": gain,
        })

    def gui_camera_type_changed(self, camera_type):
        ok = self._send_command("set_camera_type", {"camera_type": camera_type}, {"camera_type": camera_type})
        return ok
