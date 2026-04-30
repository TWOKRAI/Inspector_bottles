"""Операция преобразования цветового пространства."""

from __future__ import annotations

import cv2
import numpy as np

from multiprocess_prototype.services.processor.operations.base import ChainContext

# Маппинг режимов → (cv2-код, ожидаемое число каналов входа)
# Значение: (cv2_code, expected_channels_in)
# expected_channels_in = None означает любое число каналов
_MODE_MAP: dict[str, tuple[int, int | None]] = {
    "bgr2gray": (cv2.COLOR_BGR2GRAY, 3),
    "bgr2hsv": (cv2.COLOR_BGR2HSV, 3),
    "bgr2rgb": (cv2.COLOR_BGR2RGB, 3),
    "gray2bgr": (cv2.COLOR_GRAY2BGR, 1),
}


class ColorConvertOp:
    """Операция конвертации цветового пространства кадра.

    Поддерживаемые режимы: bgr2gray, bgr2hsv, bgr2rgb, gray2bgr.
    Если кадр не соответствует ожидаемому числу каналов — добавляется предупреждение
    в context.warnings и кадр возвращается без изменений.
    """

    def __init__(self) -> None:
        self._mode: str = "bgr2gray"
        self._cv2_code: int = cv2.COLOR_BGR2GRAY
        self._expected_channels: int | None = 3

    def configure(self, params: dict) -> None:
        """Применить параметры: mode."""
        self._mode = params.get("mode", "bgr2gray")
        code, channels = _MODE_MAP.get(self._mode, (cv2.COLOR_BGR2GRAY, 3))
        self._cv2_code = code
        self._expected_channels = channels

    def execute(self, frame: np.ndarray, context: ChainContext) -> np.ndarray:
        """Конвертировать цветовое пространство кадра."""
        actual_channels = 1 if frame.ndim == 2 else frame.shape[2]

        if self._expected_channels is not None and actual_channels != self._expected_channels:
            context.warnings.append(
                f"ColorConvertOp: режим '{self._mode}' ожидает {self._expected_channels} каналов, "
                f"получено {actual_channels} — кадр возвращён без изменений."
            )
            return frame

        return cv2.cvtColor(frame, self._cv2_code)


__all__ = ["ColorConvertOp"]
