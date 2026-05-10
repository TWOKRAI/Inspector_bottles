"""GUI command payload catalog (builders for command args/data)."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from multiprocess_prototype.registers.camera import (
    WEBCAM_ENUM_DEFAULT_MAX_INDEX,
    WEBCAM_ENUM_HARD_CAP,
)


def _args_empty() -> Dict[str, Any]:
    return {}


def _args_color_range(b_l: int, g_l: int, r_l: int, b_u: int, g_u: int, r_u: int) -> Dict[str, Any]:
    return {"color_lower": [b_l, g_l, r_l], "color_upper": [b_u, g_u, r_u]}


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


def _args_process_name(process_name: str = "") -> Dict[str, Any]:
    return {"process_name": process_name}


def _args_process_create(
    process_name: str = "",
    class_path: str = "",
    config: dict | None = None,
    priority: str = "normal",
) -> Dict[str, Any]:
    """Аргументы команды создания нового процесса."""
    result: Dict[str, Any] = {
        "process_name": process_name,
        "class_path": class_path,
        "priority": priority,
    }
    if config is not None:
        result["config"] = config
    return result


def _args_passthrough(**kwargs) -> Dict[str, Any]:
    """Передать kwargs как есть — используется для уже сформированных payload."""
    return kwargs


def _args_enum_devices(
    max_index: int = WEBCAM_ENUM_DEFAULT_MAX_INDEX,
    backend: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        n = int(max_index)
    except (TypeError, ValueError):
        n = WEBCAM_ENUM_DEFAULT_MAX_INDEX
    n = max(1, min(n, WEBCAM_ENUM_HARD_CAP))
    out: Dict[str, Any] = {"max_index": n}
    if backend in ("webcam", "hikvision"):
        out["backend"] = backend
    return out


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
    "enum_devices": _args_enum_devices,
    "open": _args_camera_index,
    "close": _args_empty,
    "start_grabbing": _args_empty,
    "stop_grabbing": _args_empty,
    "get_parameters": _args_empty,
    "set_parameters": _args_parameters,
    "set_camera_type": _args_camera_type,
    "restart_all": _args_empty,
    "process.list": _args_empty,
    "process.status": _args_process_name,
    "system.stats": _args_empty,
    "system.shutdown": _args_empty,
    "process.start": _args_process_name,
    "process.stop": _args_process_name,
    "process.restart": _args_process_name,
    "process.create": _args_process_create,
    "process.pause": _args_process_name,
    "process.resume": _args_process_name,
    # Обёртка для Router-endpoint ProcessManager: data уже сформирована в _send_pm_command
    "process.command": _args_passthrough,
}


__all__ = ["GUI_COMMAND_CATALOG"]
