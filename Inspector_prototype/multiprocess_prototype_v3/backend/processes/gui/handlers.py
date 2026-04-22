"""Обработчики входящих data-сообщений для GuiProcess.

Каждая функция принимает зависимости как аргументы (window, log_error, etc.)
и обновляет UI. Dispatch по data_type — в process.py через HANDLER_MAP.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

import numpy as np


def handle_camera_status(window: Any, data: dict) -> None:
    """Обновить статус камеры в окне."""
    text = data.get("status", "")
    if window and hasattr(window, "update_camera_status"):
        window.update_camera_status(text)


def handle_camera_error(window: Any, data: dict, log_error: Callable) -> None:
    """Обработать ошибку камеры и отобразить в окне."""
    text = data.get("error", "")
    log_error(f"Camera error: {text}")
    if window and hasattr(window, "update_camera_error"):
        window.update_camera_error(text)


def handle_parameters_response(window: Any, data: dict) -> None:
    """Передать параметры камеры в окно."""
    if window and hasattr(window, "update_camera_parameters"):
        window.update_camera_parameters(data.get("parameters", {}))


def handle_enum_devices_response(window: Any, data: dict) -> None:
    """Передать список устройств в окно."""
    if window and hasattr(window, "update_camera_devices"):
        window.update_camera_devices(data.get("devices", []))


def handle_camera_type_changed(window: Any, data: dict) -> None:
    """Синхронизировать тип камеры в окне."""
    if window and hasattr(window, "sync_camera_type"):
        window.sync_camera_type(data.get("camera_type", "simulator"))


def handle_fps_update(window: Any, data: dict) -> None:
    """Обновить счётчик FPS в окне."""
    if window and hasattr(window, "update_camera_fps"):
        window.update_camera_fps(data.get("fps", 0))


def handle_recorder_stats(window: Any, data: dict) -> None:
    """Обновить индикатор записи в display-окнах.

    Phase 6: RecorderWorker шлёт stats → GuiProcess → display windows.
    Пока placeholder — будет задействован когда RecorderWorker начнёт
    отправлять stats через IPC.
    """
    pass  # Реализация в Phase 6.9+, когда RecorderWorker stats IPC будет готов
