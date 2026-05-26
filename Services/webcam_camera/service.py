"""WebcamCameraService — захват кадров с веб-камеры через OpenCV.

Реализует интерфейс IService (Phase 3): start / stop / get_status.
Phase 6: добавлен get_current_frame() через cv2.VideoCapture.

На Windows используется backend CAP_DSHOW во избежание зависания
при инициализации устройства (DirectShow быстрее MediaFoundation).
"""

from __future__ import annotations

import sys
from typing import Any, Optional

import numpy as np

from multiprocess_framework.modules.service_module import register_service


@register_service(name="webcam_camera")
class WebcamCameraService:
    """Сервис веб-камеры с реальным захватом кадров (Phase 6).

    Хранит конфигурацию и статус; открывает cv2.VideoCapture при start().

    Атрибуты:
        name    — идентификатор сервиса для ServiceRegistry.
        status  — текущее состояние ("stopped" | "running").
        config  — конфиг, переданный в последнем вызове start().
    """

    name: str = "webcam_camera"

    def __init__(self, logger: Optional[Any] = None) -> None:
        """Инициализация.

        Args:
            logger: объект с методами .info() / .warning() / .error().
                    Если None — логирование подавляется.
        """
        self._logger = logger
        self.status: str = "stopped"
        self.config: dict = {}
        self._cap = None  # cv2.VideoCapture | None

    # ------------------------------------------------------------------
    # Публичный API (IService-совместимый)
    # ------------------------------------------------------------------

    def start(self, config: dict) -> bool:
        """Запустить сервис с заданной конфигурацией.

        Открывает cv2.VideoCapture для устройства device_id (default=0).
        На Windows: использует CAP_DSHOW для избежания зависания.

        Args:
            config: словарь параметров (device_id, width, height, fps и т.п.).

        Returns:
            True при успехе. Возвращает True даже если камера не открылась —
            сервис переходит в "running", но get_current_frame() вернёт None.
        """
        self.config = dict(config)
        self.status = "running"

        device_id = int(config.get("device_id", 0))

        try:
            import cv2  # noqa: PLC0415 — ленивый импорт (cv2 может быть optional)

            # На Windows DirectShow backend не зависает в отличие от MediaFoundation
            if sys.platform == "win32":
                cap = cv2.VideoCapture(device_id, cv2.CAP_DSHOW)
            else:
                cap = cv2.VideoCapture(device_id)

            if cap.isOpened():
                self._cap = cap
                if self._logger:
                    self._logger.info(f"[{self.name}] start(): камера device_id={device_id} открыта")
            else:
                # Устройство не доступно — сервис работает без камеры
                cap.release()
                self._cap = None
                if self._logger:
                    self._logger.warning(f"[{self.name}] start(): камера device_id={device_id} не открылась")

        except ImportError:
            # cv2 не установлен — shell-режим
            self._cap = None
            if self._logger:
                self._logger.warning(f"[{self.name}] start(): cv2 не доступен, shell-режим")

        except Exception as exc:  # noqa: BLE001
            # Любая ошибка OpenCV — не падаем, логируем warning
            self._cap = None
            if self._logger:
                self._logger.warning(f"[{self.name}] start(): ошибка открытия камеры: {type(exc).__name__}: {exc}")

        return True

    def stop(self) -> bool:
        """Остановить сервис и освободить устройство камеры.

        Returns:
            True при успехе.
        """
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception as exc:  # noqa: BLE001
                if self._logger:
                    self._logger.warning(f"[{self.name}] stop(): ошибка release: {exc}")
            self._cap = None

        self.status = "stopped"
        if self._logger:
            self._logger.info(f"[{self.name}] stop() вызван")
        return True

    def get_status(self) -> dict:
        """Вернуть текущее состояние сервиса.

        Returns:
            Словарь с ключами name, status, config.
        """
        return {
            "name": self.name,
            "status": self.status,
            "config": self.config,
        }

    def get_current_frame(self) -> "np.ndarray | None":
        """Захватить текущий кадр с камеры.

        Безопасен при любом состоянии:
        - сервис stopped → None (без исключений)
        - _cap is None → None (камера не открылась или не установлена)
        - _cap.read() вернул ret=False → None

        Returns:
            BGR numpy array (uint8) или None если кадр недоступен.
        """
        if self.status != "running":
            return None

        if self._cap is None:
            return None

        try:
            ret, frame = self._cap.read()
            if not ret or frame is None:
                return None
            return frame
        except Exception:  # noqa: BLE001
            return None

    def __repr__(self) -> str:
        cam_open = self._cap is not None and getattr(self._cap, "isOpened", lambda: False)()
        return f"WebcamCameraService(status={self.status!r}, cam_open={cam_open})"
