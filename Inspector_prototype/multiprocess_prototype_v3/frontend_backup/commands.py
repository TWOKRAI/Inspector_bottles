"""GUI command handler and camera callbacks (merged from v2's 3 files)."""

from __future__ import annotations

from typing import Any, Callable, Dict


class GuiCommandHandler:
    """Facade for sending commands from UI widgets to backend processes."""

    def __init__(self, process_ref: Any):
        self._process = process_ref

    def start_capture(self):
        self._process.gui_start_capture()

    def stop_capture(self):
        self._process.gui_stop_capture()

    def set_fps(self, fps: int):
        self._process.gui_set_fps(fps)

    def set_camera_type(self, camera_type: str):
        self._process.gui_camera_type_changed(camera_type)

    def enum_devices(self, backend: str = None):
        if backend:
            self._process._send_command("enum_devices", {"backend": backend}, {"backend": backend})
        else:
            self._process.gui_enum_devices()

    def open_camera(self, camera_index: int = 0):
        self._process.gui_open_camera(camera_index)

    def close_camera(self):
        self._process.gui_close_camera()

    def start_grabbing(self):
        self._process.gui_start_grabbing()

    def stop_grabbing(self):
        self._process.gui_stop_grabbing()

    def get_parameters(self):
        self._process.gui_get_parameters()

    def set_parameters(self, frame_rate: float, exposure_time: float, gain: float):
        self._process.gui_set_parameters(frame_rate, exposure_time, gain)

    def set_color_range(self, b_lower, g_lower, r_lower, b_upper, g_upper, r_upper):
        self._process.gui_set_color_range(b_lower, g_lower, r_lower, b_upper, g_upper, r_upper)

    def set_min_area(self, min_area: int):
        self._process.gui_set_min_area(min_area)

    def set_max_area(self, max_area: int):
        self._process.gui_set_max_area(max_area)

    def set_show_original(self, show: bool):
        self._process.gui_set_show_original(show)

    def set_show_mask(self, show: bool):
        self._process.gui_set_show_mask(show)

    def set_draw_contours(self, draw: bool):
        self._process.gui_set_draw_contours(draw)

    def request_shutdown(self):
        self._process.gui_request_shutdown()


def build_camera_callbacks(cmd: GuiCommandHandler) -> Dict[str, Callable]:
    """Build camera tab callbacks map."""
    return {
        "start_capture": cmd.start_capture,
        "stop_capture": cmd.stop_capture,
        "set_fps": cmd.set_fps,
        "set_camera_type": cmd.set_camera_type,
        "enum_devices": cmd.enum_devices,
        "open_camera": cmd.open_camera,
        "close_camera": cmd.close_camera,
        "start_grabbing": cmd.start_grabbing,
        "stop_grabbing": cmd.stop_grabbing,
        "get_parameters": cmd.get_parameters,
        "set_parameters": cmd.set_parameters,
    }
