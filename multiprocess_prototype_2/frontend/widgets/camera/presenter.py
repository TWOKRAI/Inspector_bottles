"""CameraPresenter — MVP presenter для CameraView."""
import numpy as np
from PySide6.QtGui import QImage, QPixmap

from .view import ICameraView


class CameraPresenter:
    """Управляет CameraView: конвертирует BGR numpy → QPixmap."""

    def __init__(self, view: ICameraView):
        self._view = view

    def on_frame(self, frame: np.ndarray) -> None:
        """Получен кадр BGR. Конвертировать в QPixmap и отобразить."""
        if frame is None or frame.size == 0:
            self._view.set_placeholder("Пустой кадр")
            return

        # BGR → RGB: инвертируем порядок каналов
        rgb = frame[..., ::-1].copy()  # copy() — гарантирует contiguous memory
        h, w = rgb.shape[:2]
        bytes_per_line = 3 * w

        qimage = QImage(rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qimage)
        self._view.update_pixmap(pixmap)

    def on_no_signal(self) -> None:
        """Нет сигнала от камеры."""
        self._view.set_placeholder("Нет сигнала")
