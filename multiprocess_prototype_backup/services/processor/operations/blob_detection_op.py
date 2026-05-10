"""Stub-операция blob-детекции (заглушка для будущей реализации)."""
from __future__ import annotations

import numpy as np

from .base import ChainContext


class BlobDetectionOp:
    """Заглушка операции blob-детекции.

    Кадр возвращается без изменений, в context добавляется предупреждение.
    Предназначена как placeholder до полной реализации алгоритма.
    """

    def __init__(self) -> None:
        # Параметры, переданные через configure
        self._params: dict = {}

    def configure(self, params: dict) -> None:
        """Сохранить параметры конфигурации."""
        self._params = dict(params)

    def execute(self, frame: np.ndarray, context: ChainContext) -> np.ndarray:
        """Вернуть кадр без изменений, добавить предупреждение в context."""
        context.warnings.append("BlobDetectionOp: stub, кадр не изменён")
        return frame
