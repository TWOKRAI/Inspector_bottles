"""Операция изменения размера кадра."""

from __future__ import annotations

import cv2
import numpy as np

from multiprocess_prototype.services.processor.operations.base import ChainContext

# Маппинг строковых названий интерполяции → cv2-константы
_INTERP_MAP: dict[str, int] = {
    "nearest": cv2.INTER_NEAREST,
    "linear": cv2.INTER_LINEAR,
    "cubic": cv2.INTER_CUBIC,
    "area": cv2.INTER_AREA,
}


class ResizeOp:
    """Операция ресайза кадра до заданных размеров.

    Параметры: width, height, interpolation (nearest/linear/cubic/area).
    """

    def __init__(self) -> None:
        self._width: int = 640
        self._height: int = 480
        self._interp: int = cv2.INTER_LINEAR

    def configure(self, params: dict) -> None:
        """Применить параметры: width, height, interpolation."""
        self._width = int(params.get("width", 640))
        self._height = int(params.get("height", 480))
        interp_str = params.get("interpolation", "linear")
        self._interp = _INTERP_MAP.get(interp_str, cv2.INTER_LINEAR)

    def execute(self, frame: np.ndarray, context: ChainContext) -> np.ndarray:
        """Изменить размер кадра."""
        return cv2.resize(frame, (self._width, self._height), interpolation=self._interp)


__all__ = ["ResizeOp"]
