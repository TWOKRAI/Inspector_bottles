# multiprocess_prototype/registers/gui_command_catalog.py
"""
Каталог payload для GUI-команд (args/data для MessageAdapter.command).

Targets процессов — в ``command_routing.resolve_command_targets``; этот модуль только builders.
"""
from __future__ import annotations

from typing import Any, Callable, Dict

# command_id -> функция, возвращающая dict для args и data (кроме случаев с раздельным data в mixin)


def _args_empty() -> Dict[str, Any]:
    return {}


def _args_color_range(b_l: int, g_l: int, r_l: int, b_u: int, g_u: int, r_u: int) -> Dict[str, Any]:
    return {
        "color_lower": [b_l, g_l, r_l],
        "color_upper": [b_u, g_u, r_u],
    }


def _args_min_area(min_area: int) -> Dict[str, Any]:
    return {"min_area": min_area}


def _args_max_area(max_area: int) -> Dict[str, Any]:
    return {"max_area": max_area}


def _args_show_original(show: bool) -> Dict[str, Any]:
    return {"show_original": show}


def _args_show_mask(show: bool) -> Dict[str, Any]:
    return {"show_mask": show}


def _args_draw_contours(draw: bool) -> Dict[str, Any]:
    return {"draw_contours": draw}


def _args_fps(fps: int) -> Dict[str, Any]:
    return {"fps": fps}


def _args_camera_index(camera_index: int = 0) -> Dict[str, Any]:
    return {"camera_index": camera_index}


def _args_parameters(frame_rate: float, exposure_time: float, gain: float) -> Dict[str, Any]:
    return {"frame_rate": frame_rate, "exposure_time": exposure_time, "gain": gain}


def _args_camera_type(camera_type: str) -> Dict[str, Any]:
    return {"camera_type": camera_type}


GUI_COMMAND_CATALOG: Dict[str, Callable[..., Dict[str, Any]]] = {
    "start_capture": _args_empty,
    "stop_capture": _args_empty,
    "set_fps": _args_fps,
    "set_color_range": _args_color_range,
    "set_min_area": _args_min_area,
    "set_max_area": _args_max_area,
    "set_show_original": _args_show_original,
    "set_show_mask": _args_show_mask,
    "set_draw_contours": _args_draw_contours,
    "enum_devices": _args_empty,
    "open": _args_camera_index,
    "close": _args_empty,
    "start_grabbing": _args_empty,
    "stop_grabbing": _args_empty,
    "get_parameters": _args_empty,
    "set_parameters": _args_parameters,
    "set_camera_type": _args_camera_type,
}
