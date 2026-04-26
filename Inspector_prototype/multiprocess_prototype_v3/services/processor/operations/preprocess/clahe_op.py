"""Операция выравнивания гистограммы CLAHE."""

from __future__ import annotations

import cv2
import numpy as np

from multiprocess_prototype_v3.services.processor.operations.base import ChainContext


class ClaheOp:
    """Операция CLAHE (Contrast Limited Adaptive Histogram Equalization).

    Принимает grayscale-кадр. Если на вход поступает BGR-кадр — выполняется
    конвертация по L-каналу в цветовом пространстве LAB (стандартная техника):
      1. BGR → LAB
      2. CLAHE применяется к L-каналу
      3. LAB → BGR

    Это сохраняет цветовую информацию. Предупреждение в context.warnings НЕ добавляется
    при BGR-входе — это нормальный сценарий использования.

    Если входной кадр уже grayscale (2D или 1 канал) — CLAHE применяется напрямую,
    выход остаётся grayscale.
    """

    def __init__(self) -> None:
        self._clip_limit: float = 2.0
        self._tile_grid_size: int = 8
        self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

    def configure(self, params: dict) -> None:
        """Применить параметры: clip_limit, tile_grid_size."""
        self._clip_limit = float(params.get("clip_limit", 2.0))
        self._tile_grid_size = int(params.get("tile_grid_size", 8))
        self._clahe = cv2.createCLAHE(
            clipLimit=self._clip_limit,
            tileGridSize=(self._tile_grid_size, self._tile_grid_size),
        )

    def execute(self, frame: np.ndarray, context: ChainContext) -> np.ndarray:
        """Применить CLAHE к кадру.

        Grayscale: CLAHE напрямую.
        BGR: CLAHE по L-каналу LAB с последующей обратной конвертацией.
        """
        is_gray = frame.ndim == 2 or (frame.ndim == 3 and frame.shape[2] == 1)

        if is_gray:
            # Обеспечиваем 2D
            gray = frame if frame.ndim == 2 else frame[:, :, 0]
            return self._clahe.apply(gray)
        else:
            # BGR → LAB → CLAHE на L → обратно в BGR
            lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
            l_channel, a_channel, b_channel = cv2.split(lab)
            l_eq = self._clahe.apply(l_channel)
            lab_eq = cv2.merge([l_eq, a_channel, b_channel])
            return cv2.cvtColor(lab_eq, cv2.COLOR_LAB2BGR)


__all__ = ["ClaheOp"]
