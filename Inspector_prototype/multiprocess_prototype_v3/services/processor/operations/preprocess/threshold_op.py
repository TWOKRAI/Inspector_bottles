"""Операция пороговой бинаризации кадра."""

from __future__ import annotations

import cv2
import numpy as np

from multiprocess_prototype_v3.services.processor.operations.base import ChainContext

# Маппинг строковых режимов → cv2-флаги threshold
_THRESH_MODE_MAP: dict[str, int] = {
    "binary": cv2.THRESH_BINARY,
    "binary_inv": cv2.THRESH_BINARY_INV,
    "trunc": cv2.THRESH_TRUNC,
    "tozero": cv2.THRESH_TOZERO,
    "otsu": cv2.THRESH_BINARY + cv2.THRESH_OTSU,
}


class ThresholdOp:
    """Операция пороговой бинаризации (cv2.threshold).

    Принимает grayscale-кадр. Если на вход поступает BGR-кадр — конвертируется
    в grayscale с добавлением предупреждения в context.warnings.

    Возвращает бинарную маску (uint8, значения 0 и max_value).
    """

    def __init__(self) -> None:
        self._thresh_value: float = 128.0
        self._max_value: float = 255.0
        self._mode_flag: int = cv2.THRESH_BINARY

    def configure(self, params: dict) -> None:
        """Применить параметры: thresh_value, max_value, mode."""
        self._thresh_value = float(params.get("thresh_value", 128.0))
        self._max_value = float(params.get("max_value", 255.0))
        mode_str = params.get("mode", "binary")
        self._mode_flag = _THRESH_MODE_MAP.get(mode_str, cv2.THRESH_BINARY)

    def execute(self, frame: np.ndarray, context: ChainContext) -> np.ndarray:
        """Применить пороговую бинаризацию. Возвращает бинарную маску."""
        # Конвертируем в grayscale если нужно
        is_gray = frame.ndim == 2 or (frame.ndim == 3 and frame.shape[2] == 1)
        if not is_gray:
            context.warnings.append(
                "ThresholdOp: получен BGR-кадр, конвертируется в grayscale перед бинаризацией."
            )
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame if frame.ndim == 2 else frame[:, :, 0]

        _, binary = cv2.threshold(gray, self._thresh_value, self._max_value, self._mode_flag)
        return binary


__all__ = ["ThresholdOp"]
