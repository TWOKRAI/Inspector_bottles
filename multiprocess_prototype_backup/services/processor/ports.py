"""Выходные порты процессора."""
from __future__ import annotations
from typing import Optional, Protocol

import numpy as np


class ProcessorOutputPort(Protocol):
    """Порт для коммуникации ProcessorService с внешним миром."""

    def send_detection_to_renderer(self, result_data: dict) -> None:
        """Отправить результат детекции рендереру."""
        ...

    def send_detections_to_database(self, rows: list[dict]) -> None:
        """Отправить детекции в базу данных."""
        ...

    def send_feedback_to_camera(self, frame_id: int, processing_time: float) -> None:
        """Отправить feedback камере (время обработки)."""
        ...

    def write_mask_to_shm(self, mask: np.ndarray) -> tuple[Optional[str], int]:
        """Записать маску в SHM. Возвращает (shm_name, shm_index)."""
        ...
