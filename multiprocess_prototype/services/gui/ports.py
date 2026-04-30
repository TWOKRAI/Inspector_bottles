"""Выходные порты GUI."""
from __future__ import annotations
from typing import Any, Optional, Protocol

import numpy as np


class GuiOutputPort(Protocol):
    """Порт для коммуникации GuiService с внешним миром."""

    def send_command(self, target: str, command: str, args: dict[str, Any], data: dict[str, Any]) -> bool:
        """Отправить команду целевому процессу."""
        ...

    def read_shm_images(self, owner: str, slot: str, index: int) -> Optional[list[np.ndarray]]:
        """Прочитать изображения из SHM."""
        ...
