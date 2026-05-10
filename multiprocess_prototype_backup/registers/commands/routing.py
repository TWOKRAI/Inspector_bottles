"""GUI command → target process routing."""

from __future__ import annotations

from typing import Dict, List

COMMAND_TO_REGISTER_KEY: Dict[str, str] = {
    "start_capture": "camera",
    "stop_capture": "camera",
    "set_fps": "camera",
    "set_color_range": "processor",
    "set_min_area": "processor",
    "set_max_area": "processor",
    "set_show_original": "renderer",
    "set_show_mask": "renderer",
    "set_draw_contours": "renderer",
    "set_draw_bboxes": "renderer",
    "set_save_frames": "renderer",
    "enum_devices": "camera",
    "open": "camera",
    "close": "camera",
    "start_grabbing": "camera",
    "stop_grabbing": "camera",
    "get_parameters": "camera",
    "set_parameters": "camera",
    "set_camera_type": "camera",
}

EXPLICIT_COMMAND_TARGETS: Dict[str, List[str]] = {
    "system.shutdown": ["ProcessManager"],
    "restart_all": ["ProcessManager"],
    "process.list": ["ProcessManager"],
    "process.status": ["ProcessManager"],
    "system.stats": ["ProcessManager"],
    "process.start": ["ProcessManager"],
    "process.stop": ["ProcessManager"],
    "process.restart": ["ProcessManager"],
    "process.create": ["ProcessManager"],
    "process.pause": ["ProcessManager"],
    "process.resume": ["ProcessManager"],
    # Обёртка для маршрутизации команд через Router-endpoint ProcessManager (AD-8)
    "process.command": ["ProcessManager"],
}


def list_gui_command_ids() -> List[str]:
    return sorted(set(COMMAND_TO_REGISTER_KEY) | set(EXPLICIT_COMMAND_TARGETS))


def resolve_command_targets(command_id: str) -> List[str]:
    if command_id in EXPLICIT_COMMAND_TARGETS:
        return list(EXPLICIT_COMMAND_TARGETS[command_id])
    key = COMMAND_TO_REGISTER_KEY[command_id]
    return [key]


__all__ = [
    "COMMAND_TO_REGISTER_KEY",
    "EXPLICIT_COMMAND_TARGETS",
    "list_gui_command_ids",
    "resolve_command_targets",
]
