# multiprocess_prototype/frontend/widgets/hikvision_widget/callbacks.py
"""Интерфейс колбэков HikvisionWidget."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from multiprocess_prototype.camera_policy import WEBCAM_ENUM_DEFAULT_MAX_INDEX


@dataclass(frozen=True)
class HikvisionWidgetCallbacks:
    """Колбэки Hikvision: устройства, Open/Close, Grabbing, параметры."""

    on_enum_devices: Optional[Callable[[], None]] = None
    on_open: Optional[Callable[..., None]] = None
    on_close: Optional[Callable[[], None]] = None
    on_start_grabbing: Optional[Callable[[], None]] = None
    on_stop_grabbing: Optional[Callable[[], None]] = None
    on_get_parameters: Optional[Callable[[], None]] = None
    on_set_parameters: Optional[Callable[[float, float, float], None]] = None


def build_hikvision_callbacks(
    cmd,
    *,
    webcam_enum_max_index: int = WEBCAM_ENUM_DEFAULT_MAX_INDEX,
) -> HikvisionWidgetCallbacks:
    """Собрать колбэки из GuiCommandHandler для Hikvision."""
    return HikvisionWidgetCallbacks(
        on_enum_devices=lambda: cmd.send_enum_devices(
            max_index=webcam_enum_max_index, backend="hikvision"
        ),
        on_open=lambda camera_index=0: cmd.send_open_camera(camera_index=camera_index),
        on_close=cmd.send_close_camera,
        on_start_grabbing=cmd.send_start_grabbing,
        on_stop_grabbing=cmd.send_stop_grabbing,
        on_get_parameters=cmd.send_get_parameters,
        on_set_parameters=lambda fr, exp, gain: cmd.send_set_parameters(fr, exp, gain),
    )
