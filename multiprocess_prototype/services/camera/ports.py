"""Выходные порты камеры."""
from __future__ import annotations
from typing import Optional, Protocol

import numpy as np


class CameraOutputPort(Protocol):
    """Порт для коммуникации CameraService с внешним миром."""

    def send_frame_to_processor(self, data: dict) -> None:
        """Отправить уведомление о новом кадре процессору."""
        ...

    def send_to_gui(self, msg_type: str, data: dict) -> None:
        """Отправить сообщение в GUI (статус, fps, ошибки)."""
        ...

    def write_frame_to_shm(self, frame: np.ndarray, frame_id: int, timestamp: float) -> Optional[dict]:
        """Записать кадр в SHM. Возвращает dict с shm_name, shm_index, shm_actual_name или None."""
        ...

    def request_shm_resize(self, new_width: int, new_height: int) -> None:
        """Запросить пересоздание SHM-региона под новое разрешение.

        Отправляет shm_region_change_request в ProcessManager.
        Camera продолжает resize к старым размерам до получения ответа.
        """
        ...
