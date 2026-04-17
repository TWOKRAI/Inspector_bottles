# -*- coding: utf-8 -*-
"""Маршрутизация id GUI-команды → целевые процессы (имена как в SystemLauncher)."""

from __future__ import annotations

from typing import Dict, List

# Команда → ключ регистра (имя процесса-получателя)
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
}


def list_gui_command_ids() -> List[str]:
    return sorted(set(COMMAND_TO_REGISTER_KEY) | set(EXPLICIT_COMMAND_TARGETS))


def resolve_command_targets(command_id: str) -> List[str]:
    if command_id in EXPLICIT_COMMAND_TARGETS:
        return list(EXPLICIT_COMMAND_TARGETS[command_id])
    key = COMMAND_TO_REGISTER_KEY[command_id]
    return [key]
