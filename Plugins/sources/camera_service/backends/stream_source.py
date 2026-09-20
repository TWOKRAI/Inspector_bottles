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

# Отключить внутреннюю буферизацию FFmpeg-бэкенда cv2 (nobuffer/low_delay).
# ЗАМЕР ведущего 2026-09-21 (инъекция: строка снята, 4 прогона на каждом варианте,
# харнесс приёмочного теста): БЕЗ неё после обрыва источника доезжает 2 кадра и обрыв
# замечается за 0.11 с; С ней — 1 кадр и 0.06 с. То есть она вдвое сокращает и доезд,
# и задержку обнаружения обрыва — для камеры инспекции это латентность, а не косметика.
# Приёмка зелёная в ОБОИХ вариантах: тест сторожит «доезд ограничен и обрыв замечен»,
# а не конкретный тюнинг — это намеренно, иначе тест пришпилил бы тайминг машины.
#
# ЦЕНА, которую надо знать: это переменная окружения ПРОЦЕССА, выставляемая побочным
# эффектом импорта модуля, и ffmpeg-контекст cv2 читает её один раз при инициализации.
# setdefault не перебьёт чужое значение — но и своё не применит, если кто-то выставил
# другое РАНЬШЕ. Грепом других писателей этой переменной в дереве нет (webcam/hikvision
# её не трогают), так что сегодня конфликта не существует; при появлении второго
# писателя выиграет тот, кто импортировался первым, и это будет незаметно.
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
