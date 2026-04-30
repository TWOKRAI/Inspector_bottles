# multiprocess_prototype/frontend/widgets/camera_common/callbacks.py
"""
Колбэки Simulator/Webcam: один контракт; различие по camera_type в регистре.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class SimWebcamWidgetCallbacks:
    """Start, Stop, Set FPS — общие для симулятора и веб-камеры."""

    on_start: Optional[Callable[[], None]] = None
    on_stop: Optional[Callable[[], None]] = None
    on_set_fps: Optional[Callable[[int], None]] = None


def build_sim_webcam_callbacks(cmd) -> SimWebcamWidgetCallbacks:
    """Собрать колбэки из GuiCommandHandler."""
    return SimWebcamWidgetCallbacks(
        on_start=cmd.send_start_capture,
        on_stop=cmd.send_stop_capture,
        on_set_fps=cmd.send_set_fps,
    )
