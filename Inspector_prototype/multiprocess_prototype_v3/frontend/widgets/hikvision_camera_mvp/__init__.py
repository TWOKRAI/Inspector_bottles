# multiprocess_prototype_v3/frontend/widgets/hikvision_camera_mvp/
"""
Виджет Hikvision (MVP): границы параметров из CameraRegisters; команды через GuiCommandHandler.

Legacy: ``hikvision_widget`` (колбэки) остаётся без изменений.

Виджет импортируется лениво (``__getattr__``), чтобы ``schemas`` можно было подключать в CameraTabUiConfig без Qt.
"""
from __future__ import annotations

from .schemas import HikvisionCameraMvpUiConfig

__all__ = [
    "HikvisionCameraMvpWidget",
    "HikvisionCameraMvpUiConfig",
]


def __getattr__(name: str):
    if name == "HikvisionCameraMvpWidget":
        from .widget import HikvisionCameraMvpWidget as _W

        return _W
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
