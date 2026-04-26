"""Операция гауссова размытия кадра."""

from __future__ import annotations

import cv2
import numpy as np

from multiprocess_prototype_v3.services.processor.operations.base import ChainContext


class BlurOp:
    """Операция гауссова размытия (GaussianBlur).

    Параметры: kernel_size (нечётное число), sigma.
    Если kernel_size чётный — автоматически увеличивается на 1 и добавляется
    предупреждение в context.warnings.
    """

    def __init__(self) -> None:
        self._kernel_size: int = 5
        self._sigma: float = 0.0

    def configure(self, params: dict) -> None:
        """Применить параметры: kernel_size, sigma."""
        self._kernel_size = int(params.get("kernel_size", 5))
        self._sigma = float(params.get("sigma", 0.0))

    def execute(self, frame: np.ndarray, context: ChainContext) -> np.ndarray:
        """Применить гауссово размытие."""
        k = self._kernel_size
        if k % 2 == 0:
            k = k + 1
            context.warnings.append(
                f"BlurOp: kernel_size должен быть нечётным, использован {k} вместо {self._kernel_size}."
            )
        return cv2.GaussianBlur(frame, (k, k), self._sigma)


__all__ = ["BlurOp"]
