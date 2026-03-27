# multiprocess_prototype/frontend/widgets/camera_tab/
"""
Вкладка камеры: контейнер с переключателем Simulator/Webcam/Hikvision.

camera_common (SimWebcamWidget) и hikvision_widget; callbacks_map через build_camera_tab_callbacks.
"""

from multiprocess_prototype.camera_policy import WEBCAM_ENUM_DEFAULT_MAX_INDEX

from .schemas import CameraTabUiConfig
from .widget import CameraTabWidget


def build_camera_tab_callbacks(
    cmd,
    *,
    webcam_enum_max_index: int = WEBCAM_ENUM_DEFAULT_MAX_INDEX,
) -> dict:
    """Собрать callbacks_map для CameraTabWidget из GuiCommandHandler (Sim/Webcam + смена типа камеры).

    Hikvision обслуживается HikvisionCameraMvpWidget через command_handler; колбэки hikvision не нужны.

    ``webcam_enum_max_index`` оставлен для совместимости вызовов (launcher); для Hikvision используется
    ``CameraTabUiConfig.webcam_enum_max_index`` во вкладке.
    """
    _ = webcam_enum_max_index
    from ...camera_common import build_sim_webcam_callbacks

    sim_web = build_sim_webcam_callbacks(cmd)
    return {
        "simulator": sim_web,
        "webcam": sim_web,
        "on_camera_type_changed": cmd.send_camera_type_changed,
    }


__all__ = [
    "CameraTabWidget",
    "CameraTabUiConfig",
    "build_camera_tab_callbacks",
]
