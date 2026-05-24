"""WebcamCameraService — минимальный shell-класс для ServiceRegistry.

Реализует интерфейс IService (Phase 3): start / stop / get_status.
Детальная реализация с реальным захватом кадров — Phase 6.

# TODO Phase 6: интегрировать CameraService из backup с полным бэкендом (webcam/hikvision/simulator)
"""

from __future__ import annotations

from typing import Any, Optional


class WebcamCameraService:
    """Shell-сервис веб-камеры.

    Хранит конфигурацию и статус; реальный бэкенд подключается в Phase 6.

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
                    Если None — логирование подавляется (shell-режим).
        """
        self._logger = logger
        self.status: str = "stopped"
        self.config: dict = {}

    # ------------------------------------------------------------------
    # Публичный API (IService-совместимый)
    # ------------------------------------------------------------------

    def start(self, config: dict) -> bool:
        """Запустить сервис с заданной конфигурацией.

        Сохраняет конфиг и переводит статус в "running".
        Реальное открытие камеры — Phase 6.

        Args:
            config: словарь параметров (device_id, width, height, fps и т.п.).

        Returns:
            True при успехе (shell всегда возвращает True).
        """
        self.config = dict(config)
        self.status = "running"
        if self._logger:
            self._logger.info(f"[{self.name}] start() вызван, config={self.config!r}")
        return True

    def stop(self) -> bool:
        """Остановить сервис.

        Переводит статус в "stopped".
        Реальное освобождение устройства — Phase 6.

        Returns:
            True при успехе (shell всегда возвращает True).
        """
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

    def __repr__(self) -> str:
        return f"WebcamCameraService(status={self.status!r})"
