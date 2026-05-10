"""Backends для CameraServicePlugin — factory, константы, re-exports."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import CameraBackend
from .simulator import SimulatorBackend
from .webcam import WebcamBackend
from .file_source import FileSourceBackend

if TYPE_CHECKING:
    pass

# Допустимые типы камер
CAMERA_TYPES: tuple[str, ...] = ("simulator", "webcam", "hikvision", "file")
DEFAULT_CAMERA_TYPE: str = "simulator"

# Задержка после освобождения аппаратного устройства (секунды).
# Нужна чтобы ОС/драйвер успели отпустить устройство перед повторным открытием.
_HW_RELEASE_DELAY: dict[str, float] = {
    "webcam": 0.3,
    "hikvision": 0.3,
}


def create_backend(camera_type: str, **kwargs) -> CameraBackend:
    """Создать backend по типу камеры.

    Args:
        camera_type: один из CAMERA_TYPES
        **kwargs: параметры для конкретного backend'а

    Returns:
        Экземпляр CameraBackend
    """
    if camera_type not in CAMERA_TYPES:
        camera_type = DEFAULT_CAMERA_TYPE

    if camera_type == "webcam":
        return WebcamBackend(
            width=kwargs.get("width", 640),
            height=kwargs.get("height", 480),
            device_id=kwargs.get("device_id", 0),
        )

    if camera_type == "hikvision":
        # Lazy import — SDK может отсутствовать
        from .hikvision import HikvisionBackend
        return HikvisionBackend(
            camera_index=kwargs.get("camera_index", 0),
            target_width=kwargs.get("width", 1920),
            target_height=kwargs.get("height", 1080),
        )

    if camera_type == "file":
        return FileSourceBackend(
            file_path=kwargs.get("file_path", ""),
        )

    # default → simulator
    return SimulatorBackend(
        width=kwargs.get("width", 640),
        height=kwargs.get("height", 480),
        image_path=kwargs.get("image_path"),
    )


def hw_release_delay(camera_type: str) -> float:
    """Получить задержку после освобождения устройства (секунды)."""
    return _HW_RELEASE_DELAY.get(camera_type, 0.0)


__all__ = [
    "CameraBackend",
    "SimulatorBackend",
    "WebcamBackend",
    "FileSourceBackend",
    "create_backend",
    "hw_release_delay",
    "CAMERA_TYPES",
    "DEFAULT_CAMERA_TYPE",
]
