"""Выходные порты рендерера."""
from __future__ import annotations
from typing import Optional, Protocol

import numpy as np


class RendererOutputPort(Protocol):
    """Порт для коммуникации RendererService с внешним миром."""

    def send_rendered_to_gui(self, notification_data: dict) -> None:
        """Отправить уведомление о готовом кадре в GUI."""
        ...

    def send_reject_to_robot(self, frame_id: int, defects: list[dict]) -> None:
        """Отправить команду отбраковки роботу."""
        ...

    def write_rendered_to_shm(self, frame: np.ndarray, mask: np.ndarray) -> Optional[dict]:
        """Записать отрендеренный кадр и маску в SHM. Возвращает dict с shm-данными."""
        ...
