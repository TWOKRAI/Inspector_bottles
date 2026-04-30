# -*- coding: utf-8 -*-
"""
Публичные контракты hikvision_camera_module.

Единственный файл, от которого должны зависеть внешние модули.
"""

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional

import numpy as np


class IHikvisionCameraFacade(ABC):
    """
    Контракт фасада Hikvision камеры.

    Инкапсулирует работу с Hikvision SDK (MvCamera).
    Все методы возвращают dict (Dict at Boundary).
    capture_frame возвращает сырой np.ndarray без cv2-конвертации.
    """

    @abstractmethod
    def enum_devices(self) -> Dict[str, Any]:
        """
        Перечислить устройства GigE/USB.
        Returns: {status: "ok"|"error", devices: [{index, type, display_name, ...}]}
        """
        ...

    @abstractmethod
    def open(self, camera_index: int = 0) -> Dict[str, Any]:
        """
        Открыть камеру по индексу.
        Returns: {status: "ok"|"error"}
        """
        ...

    @abstractmethod
    def close(self) -> Dict[str, Any]:
        """
        Закрыть камеру.
        Returns: {status: "ok"}
        """
        ...

    @abstractmethod
    def start_grabbing(self) -> Dict[str, Any]:
        """
        Начать захват кадров.
        Returns: {status: "ok"|"error"}
        """
        ...

    @abstractmethod
    def stop_grabbing(self) -> Dict[str, Any]:
        """
        Остановить захват кадров.
        Returns: {status: "ok"}
        """
        ...

    @abstractmethod
    def capture_frame(self, timeout_ms: int = 1000) -> Optional[np.ndarray]:
        """
        Захватить один кадр. Сырой массив (2D Bayer/Gray, 3D RGB — без cv2).
        Returns: np.ndarray | None
        """
        ...

    @abstractmethod
    def get_parameters(self) -> Dict[str, Any]:
        """
        Получить параметры камеры.
        Returns: {status: "ok"|"error", parameters: {frame_rate, exposure_time, gain}}
        """
        ...

    @abstractmethod
    def set_parameters(
        self,
        frame_rate: float,
        exposure_time: float,
        gain: float,
    ) -> Dict[str, Any]:
        """
        Установить параметры камеры.
        Returns: {status: "ok"|"error"}
        """
        ...

    def open_sdk_window(self) -> Dict[str, Any]:
        """
        Открыть окно оригинального SDK (Clean Camera Test).
        Returns: {status: "ok"|"error", message: str}
        """
        ...

    def close_sdk_window(self) -> Dict[str, Any]:
        """
        Закрыть окно оригинального SDK.
        Returns: {status: "ok"|"error"}
        """
        ...
