# multiprocess_prototype/frontend/widgets/tabs_setting/camera_tab/
"""
Вкладка камеры: контейнер с переключателем Simulator/Webcam/Hikvision.

camera_common (SimWebcamWidget) и hikvision_widget; callbacks_map через build_camera_tab_callbacks.
"""

from .schemas import CameraTabUiConfig
from .widget import CameraTabWidget


def build_camera_tab_callbacks(cmd) -> dict:
    """Собрать callbacks_map для CameraTabWidget из GuiCommandHandler."""
    from ...hikvision_widget import build_hikvision_callbacks
    from ...camera_common import build_sim_webcam_callbacks

    sim_web = build_sim_webcam_callbacks(cmd)
    return {
        "simulator": sim_web,
        "webcam": sim_web,
        "hikvision": build_hikvision_callbacks(cmd),
        "on_camera_type_changed": cmd.send_camera_type_changed,
    }


__all__ = [
    "CameraTabWidget",
    "CameraTabUiConfig",
    "build_camera_tab_callbacks",
]
