"""register_update для CameraRegisters — имена полей как в registers/schemas/camera_tab."""

from __future__ import annotations

from typing import Any, Callable

from multiprocess_prototype_v2.app_registers.camera_tab.names import CAMERA_REGISTER


def apply_camera_register_update(
    data: dict,
    *,
    set_camera_type: Callable[[dict], Any],
    set_fps: Callable[[dict], Any],
    set_resolution: Callable[[dict], Any],
    set_device_id: Callable[[dict], Any],
    set_camera_index: Callable[[dict], Any],
    set_hikvision_resolution: Callable[[dict], Any],
    patch_hikvision_params: Callable[[dict], Any],
) -> None:
    """Применить register_update к состоянию процесса камеры."""
    if data.get("register_name") != CAMERA_REGISTER:
        return
    field = data.get("field_name")
    value = data.get("value")
    if field == "camera_type":
        set_camera_type({"camera_type": value})
    elif field == "fps":
        set_fps({"fps": value})
    elif field == "resolution_width":
        set_resolution({"width": value})
    elif field == "resolution_height":
        set_resolution({"height": value})
    elif field == "device_id":
        set_device_id({"device_id": value})
    elif field == "camera_index":
        set_camera_index({"camera_index": value})
    elif field == "hikvision_resolution_width":
        set_hikvision_resolution({"width": value})
    elif field == "hikvision_resolution_height":
        set_hikvision_resolution({"height": value})
    elif field == "hikvision_frame_rate":
        patch_hikvision_params({"frame_rate": value})
    elif field == "hikvision_exposure_time":
        patch_hikvision_params({"exposure_time": value})
    elif field == "hikvision_gain":
        patch_hikvision_params({"gain": value})
