"""FileSourceBackend — захват кадров из видеофайла.

Зацикливает видео при достижении EOF (loop-on-EOF).
Бросает FileNotFoundError при start() если файл не найден.
"""

from __future__ import annotations

import contextlib
import os

import cv2
import numpy as np


class FileSourceBackend:
    """Backend для воспроизведения видеофайла в цикле.

    Используется для тестирования pipeline без реального оборудования.
    При достижении конца файла — перематывает на начало (loop).
    """

    def __init__(self, file_path: str) -> None:
        self._file_path = file_path
        self._cap: cv2.VideoCapture | None = None
        self._running = False

    def start(self) -> None:
        """Открыть видеофайл.

        Raises:
            FileNotFoundError: если файл не найден
            OSError: если cv2 не может открыть файл
        """
        if not os.path.isfile(self._file_path):
            raise FileNotFoundError(
                f"FileSourceBackend: файл не найден: {self._file_path!r}"
            )

        self._cap = cv2.VideoCapture(self._file_path)
        if not self._cap.isOpened():
            self._cap = None
            raise OSError(
                f"FileSourceBackend: не удалось открыть файл: {self._file_path!r}"
            )
        self._running = True

    def capture_frame(self) -> np.ndarray | None:
        """Прочитать следующий кадр. При EOF — перемотка на начало (loop)."""
        if not self._running or self._cap is None:
            return None

        ret, frame = self._cap.read()
        if not ret:
            # EOF — перемотать на начало и попробовать ещё раз
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = self._cap.read()
            if not ret:
                return None
        return frame

    def stop(self) -> None:
        """Приостановить чтение."""
        self._running = False

    def close(self) -> None:
        """Остановить и освободить VideoCapture."""
        self._running = False
        if self._cap is not None:
            with contextlib.suppress(Exception):
                self._cap.release()
            self._cap = None

    def handle_command(self, cmd: str, data: dict) -> dict | None:
        """FileSource не поддерживает специфичных команд."""
        return None
