"""
Захват кадров с веб-камеры через OpenCV.

Используется при use_simulator=False вместо FrameGenerator.
Интерфейс совместим: generate_frame() -> np.ndarray (BGR uint8).
"""

from typing import Any, Optional

import numpy as np


class WebcamCapture:
    """Захват кадров с веб-камеры (cv2.VideoCapture)."""

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        device_id: int = 0,
    ):
        """
        Args:
            width: ширина кадра.
            height: высота кадра.
            device_id: индекс камеры (0 — первая веб-камера).
        """
        self.width = width
        self.height = height
        self.device_id = device_id
        self._frame_count = 0
        self._capture: Optional[Any] = None
        self._open()

    def _open(self) -> None:
        """Открывает VideoCapture и устанавливает разрешение."""
        try:
            import cv2
        except ImportError as e:
            raise ImportError(
                "WebcamCapture требует opencv-python. Установите: pip install opencv-python"
            ) from e

        self._capture = cv2.VideoCapture(self.device_id)
        if not self._capture.isOpened():
            raise RuntimeError(
                f"Не удалось открыть камеру device_id={self.device_id}. "
                "Проверьте подключение и доступность устройства."
            )

        self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)

    def generate_frame(self) -> np.ndarray:
        """
        Захватывает один кадр с камеры.

        Returns:
            np.ndarray: кадр (height, width, 3) BGR uint8.
        """
        if self._capture is None or not self._capture.isOpened():
            return self._fallback_frame()

        ret, frame = self._capture.read()
        if not ret or frame is None:
            return self._fallback_frame()

        self._frame_count += 1

        # Привести к нужному разрешению, если камера вернула другое
        if frame.shape[1] != self.width or frame.shape[0] != self.height:
            import cv2
            frame = cv2.resize(
                frame, (self.width, self.height), interpolation=cv2.INTER_LINEAR
            )

        if len(frame.shape) == 2:
            import cv2
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        elif frame.shape[2] == 4:
            import cv2
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

        return frame.astype(np.uint8)

    def _fallback_frame(self) -> np.ndarray:
        """Чёрный кадр при ошибке чтения."""
        return np.zeros((self.height, self.width, 3), dtype=np.uint8)

    def set_resolution(self, width: int, height: int) -> None:
        """Обновляет разрешение (переоткрывает камеру)."""
        self.width = width
        self.height = height
        self.close()
        self._open()

    def close(self) -> None:
        """Освобождает ресурсы камеры."""
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def __enter__(self) -> "WebcamCapture":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def is_opened(self) -> bool:
        """True, если камера открыта и готова к захвату."""
        return self._capture is not None and self._capture.isOpened()
