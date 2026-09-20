"""StreamSourceBackend — захват кадров из сетевого видеопотока (MJPEG/RTSP/...).

В отличие от FileSourceBackend, ``stream_url`` уходит в ``cv2.VideoCapture`` как есть,
БЕЗ сторожа ``os.path.isfile`` — сетевой адрес не файл на диске, и такая проверка
отклонила бы любой валидный URL.

Отказ открытия/обрыв чтения НЕ бросается из ``start()`` наружу: недоступный сетевой
источник — штатная ситуация в эксплуатации (не программная ошибка), поэтому
``cmd_start_capture`` не должен падать на нём. Отказ виден в ``capture_frame()``
(поднимает ``OSError``), который штатный сторож ``CameraServicePlugin.produce()``
(contain → report → degrade, ``plugin.py:152-161``) сам сводит в ``ctx.health.report_error``.
"""

from __future__ import annotations

import contextlib
import os

import cv2
import numpy as np

# Отключить внутреннюю буферизацию FFmpeg-бэкенда cv2 (nobuffer/low_delay):
# без неё после обрыва источника ffmpeg ещё какое-то время отдаёт уже принятые
# по сети, но не прочитанные кадры как валидные — cap.read() кажется живым
# уже после факта обрыва. Читается один раз при инициализации ffmpeg-контекста
# cv2, setdefault — чтобы не перебить чужую настройку, если она уже задана.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "fflags;nobuffer|flags;low_delay")


class StreamSourceBackend:
    """Backend для захвата кадров из сетевого видеопотока по URL.

    ``start()`` идемпотентен и безопасен для повторного вызова без предварительного
    ``close()`` (например, restart после разрыва соединения) — предыдущий
    ``VideoCapture`` освобождается перед созданием нового, чтобы не течь handle'ами.
    """

    def __init__(self, stream_url: str) -> None:
        self._url = stream_url
        self._cap: cv2.VideoCapture | None = None
        self._running = False

    def start(self) -> None:
        """(Пере)открыть поток. Никогда не бросает — отказ виден в capture_frame()."""
        self._release_capture()
        self._cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
        with contextlib.suppress(Exception):
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._running = True

    def capture_frame(self) -> np.ndarray | None:
        """Прочитать следующий кадр.

        Raises:
            OSError: поток не открылся или чтение оборвалось — ловит и репортит
                контейнер вызывающей стороны (produce()).
        """
        if not self._running or self._cap is None:
            return None

        if not self._cap.isOpened():
            raise OSError(f"StreamSourceBackend: поток недоступен: {self._url!r}")

        # Двойной grab: HTTP/MJPEG-транспорт ffmpeg успевает принять и решить один
        # кадр вперёд ДО фактического закрытия соединения источником (уже переданные
        # по сети байты), поэтому первый grab() после обрыва иногда ещё "жив". Второй
        # grab() бьёт по уже реально оборванному сокету и отражает текущее состояние.
        if not self._cap.grab():
            raise OSError(f"StreamSourceBackend: обрыв чтения потока: {self._url!r}")
        if not self._cap.grab():
            raise OSError(f"StreamSourceBackend: обрыв чтения потока: {self._url!r}")
        ret, frame = self._cap.retrieve()
        if not ret:
            raise OSError(f"StreamSourceBackend: обрыв чтения потока: {self._url!r}")
        return frame

    def stop(self) -> None:
        """Приостановить чтение (VideoCapture не освобождается)."""
        self._running = False

    def close(self) -> None:
        """Остановить и освободить VideoCapture."""
        self._running = False
        self._release_capture()

    def _release_capture(self) -> None:
        """Освободить текущий VideoCapture, если он есть (защита от утечки handle)."""
        if self._cap is not None:
            with contextlib.suppress(Exception):
                self._cap.release()
            self._cap = None

    def handle_command(self, cmd: str, data: dict) -> dict | None:
        """StreamSource не поддерживает специфичных команд."""
        return None
