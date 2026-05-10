"""SimulatorBackend — генерация тестовых кадров.

Движущийся красный прямоугольник + timestamp overlay.
Может использовать статическое изображение из файла.
"""

from __future__ import annotations

import time
from datetime import datetime

import cv2
import numpy as np


class FrameGenerator:
    """Генератор тестовых кадров с движущимся паттерном.

    Рисует красный прямоугольник 100x100, перемещающийся по кадру,
    и наносит timestamp текущего времени (cv2.putText).
    """

    def __init__(
        self,
        width: int,
        height: int,
        image_path: str | None = None,
    ) -> None:
        self._width = width
        self._height = height
        self._frame_count = 0
        self._static_image: np.ndarray | None = None

        if image_path:
            img = cv2.imread(image_path)
            if img is not None:
                self._static_image = cv2.resize(img, (width, height))

    def generate_frame(self) -> np.ndarray:
        """Сгенерировать один кадр с движущимся прямоугольником и timestamp."""
        self._frame_count += 1

        if self._static_image is not None:
            frame = self._static_image.copy()
        else:
            frame = np.zeros((self._height, self._width, 3), dtype=np.uint8)
            # Движущийся красный прямоугольник
            rect_w, rect_h = 100, 100
            x = (self._frame_count * 3) % max(1, self._width - rect_w)
            y = (self._frame_count * 2) % max(1, self._height - rect_h)
            frame[y : y + rect_h, x : x + rect_w] = [0, 0, 200]

        # Timestamp overlay — текущее время
        ts_text = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        cv2.putText(
            frame,
            ts_text,
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

        return frame

    def close(self) -> None:
        """Освободить ресурсы (если есть)."""
        self._static_image = None


class SimulatorBackend:
    """Backend-симулятор: генерирует тестовые BGR-кадры.

    Используется для разработки и тестирования без реального оборудования.
    """

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        image_path: str | None = None,
    ) -> None:
        self._generator = FrameGenerator(width, height, image_path=image_path)
        self._running = False

    def capture_frame(self) -> np.ndarray | None:
        """Захватить один тестовый кадр. None если backend остановлен."""
        if not self._running:
            return None
        return self._generator.generate_frame()

    def start(self) -> None:
        """Запустить генерацию кадров."""
        self._running = True

    def stop(self) -> None:
        """Приостановить генерацию."""
        self._running = False

    def close(self) -> None:
        """Полностью остановить и освободить ресурсы."""
        self._running = False
        self._generator.close()

    def handle_command(self, cmd: str, data: dict) -> dict | None:
        """Симулятор не поддерживает специфичных команд."""
        return None
