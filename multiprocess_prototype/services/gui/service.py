"""GuiService — бизнес-логика GUI-хендлеров."""
from __future__ import annotations

from typing import Any, Callable, Optional

import numpy as np


class GuiService:
    """Сервис GUI. Чтение кадров и диспетчеризация сообщений."""

    def read_frame_pair(
        self,
        data: dict,
        read_rendered_fn: Callable[[int], Optional[np.ndarray]],
        read_mask_fn: Callable[[int, str], Optional[np.ndarray]],
        read_shm_fallback_fn: Callable[[str, int, int], Optional[np.ndarray]],
    ) -> tuple[np.ndarray, np.ndarray]:
        """Прочитать пару (rendered_frame, mask_frame) из SHM-данных.

        Возвращает (original, mask) — оба гарантированно ndarray.
        """
        width, height = data.get("width", 640), data.get("height", 480)
        shm_index = data.get("shm_index", 0)

        # Rendered frame
        original = read_rendered_fn(shm_index)
        if original is None and data.get("shm_actual_name"):
            original = read_shm_fallback_fn(data["shm_actual_name"], width, height)

        # Mask frame
        mask = None
        if data.get("mask_shm_actual_name"):
            mask = read_mask_fn(data.get("mask_shm_index", 0), data["mask_shm_actual_name"])
        if mask is None and data.get("mask_shm_actual_name"):
            mask = read_shm_fallback_fn(data["mask_shm_actual_name"], width, height)

        # Fallback: чёрные кадры
        if original is None:
            original = np.zeros((height, width, 3), dtype=np.uint8)
        if mask is None:
            mask = np.zeros((height, width, 3), dtype=np.uint8)

        return original, mask

    @staticmethod
    def dispatch_data_type(data_type: str) -> Optional[str]:
        """Маппинг data_type → имя хендлера.

        Возвращает имя метода-хендлера или None если неизвестный тип.
        """
        _MAP = {
            "rendered_frame_ready": "handle_new_frame",
            "status": "handle_camera_status",
            "error": "handle_camera_error",
            "parameters_response": "handle_parameters_response",
            "enum_devices_response": "handle_enum_devices_response",
            "camera_type_changed": "handle_camera_type_changed",
            "fps_update": "handle_fps_update",
        }
        return _MAP.get(data_type)
