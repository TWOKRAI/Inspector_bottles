# -*- coding: utf-8 -*-
"""
Публичные контракты hikvision_camera.

Protocol вместо ABC — более pythonic, поддерживает structural subtyping.
Единственный файл, от которого должны зависеть внешние модули.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np

from Services.hikvision_camera.core.camera import CameraState


@runtime_checkable
class HikvisionCameraProtocol(Protocol):
    """Контракт камеры Hikvision.

    Определяет минимальный интерфейс для работы с камерой.
    Любой класс, реализующий эти методы, автоматически удовлетворяет
    протоколу (structural subtyping, без явного наследования).
    """

    @property
    def state(self) -> CameraState:
        """Текущее состояние камеры."""
        ...

    def open(self, camera_index: int = 0) -> bool:
        """Открыть камеру по индексу."""
        ...

    def close(self) -> None:
        """Закрыть камеру."""
        ...

    def start_grabbing(self) -> bool:
        """Начать захват кадров."""
        ...

    def stop_grabbing(self) -> None:
        """Остановить захват кадров."""
        ...

    def capture_frame(self, timeout_ms: int = 1000) -> tuple[np.ndarray | None, int]:
        """Захватить один кадр. Возвращает (raw_frame, pixel_type)."""
        ...
