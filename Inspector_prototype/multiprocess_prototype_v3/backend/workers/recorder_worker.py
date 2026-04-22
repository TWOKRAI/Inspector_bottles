"""RecorderWorker — запись видео через cv2.VideoWriter (AD-10).

Не наследуется от framework worker — обычный класс, lifecycle управляется
через CameraProcess. write_frame() вызывается синхронно из capture_worker.

Возможности:
- Генерация имён файлов с camera_id и timestamp
- Codec fallback chain (запрошенный → XVID → mp4v)
- Auto-split при превышении max_minutes
- Статистика: frame_count, duration, file_size
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def _resolve_fourcc(codec_name: str) -> int:
    """Разрешить fourcc-код с fallback chain.

    Пробует кодеки в порядке: запрошенный → XVID → mp4v.
    Если все возвращают -1, возвращает mp4v как безопасный дефолт.
    """
    for codec in [codec_name, "XVID", "mp4v"]:
        fourcc = cv2.VideoWriter_fourcc(*codec)
        if fourcc != -1:
            return fourcc
    # Крайний fallback — mp4v гарантированно поддерживается
    return cv2.VideoWriter_fourcc(*"mp4v")


class RecorderWorker:
    """Записывает видеопоток в файл через cv2.VideoWriter.

    Args:
        camera_id: идентификатор камеры (для именования файлов).
        recordings_dir: директория для сохранения записей.
    """

    def __init__(self, camera_id: int, recordings_dir: str = "recordings") -> None:
        self._camera_id = camera_id
        self._recordings_dir = recordings_dir
        self._writer: cv2.VideoWriter | None = None
        self._recording = False
        self._file_path = ""
        self._start_time = 0.0
        self._frame_count = 0

        # Параметры текущей сессии записи (для auto-split)
        self._codec = "mp4v"
        self._fps = 25.0
        self._width = 1920
        self._height = 1080
        self._max_minutes = 30

    def start_recording(
        self,
        codec: str = "mp4v",
        fps: float = 25.0,
        width: int = 1920,
        height: int = 1080,
        max_minutes: int = 30,
    ) -> dict:
        """Начать запись видео.

        Создаёт директорию если отсутствует, генерирует имя файла
        с camera_id и текущим временем, открывает VideoWriter.

        Returns:
            dict с status и file_path (или error).
        """
        # Если уже записываем — сначала остановить
        if self._recording:
            self.stop_recording()

        # Сохранить параметры для auto-split
        self._codec = codec
        self._fps = fps
        self._width = width
        self._height = height
        self._max_minutes = max_minutes

        return self._open_writer()

    def _open_writer(self) -> dict:
        """Открыть новый VideoWriter с текущими параметрами.

        Внутренний метод — используется и из start_recording, и из auto-split.

        Returns:
            dict с status и file_path (или error).
        """
        # Гарантировать наличие директории
        Path(self._recordings_dir).mkdir(parents=True, exist_ok=True)

        # Имя файла: camera_{id}_{YYYYMMDD_HHMMSS}.mp4
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"camera_{self._camera_id}_{ts}.mp4"
        self._file_path = os.path.join(self._recordings_dir, filename)

        # Открыть writer
        fourcc = _resolve_fourcc(self._codec)
        self._writer = cv2.VideoWriter(
            self._file_path, fourcc, self._fps, (self._width, self._height)
        )

        if not self._writer.isOpened():
            logger.error(
                "RecorderWorker[%d]: не удалось открыть VideoWriter — %s",
                self._camera_id,
                self._file_path,
            )
            self._writer = None
            return {"status": "error", "error": "VideoWriter failed to open"}

        self._recording = True
        self._start_time = time.monotonic()
        self._frame_count = 0

        logger.info(
            "RecorderWorker[%d]: запись начата — %s (codec=%s, %dx%d@%.1ffps, max=%dмин)",
            self._camera_id,
            self._file_path,
            self._codec,
            self._width,
            self._height,
            self._fps,
            self._max_minutes,
        )
        return {"status": "ok", "file_path": self._file_path}

    def write_frame(self, frame: np.ndarray) -> None:
        """Записать один кадр в файл.

        Если запись не активна — ничего не делает.
        При превышении max_minutes — автоматически разделяет файл
        (stop текущий + start новый).
        """
        if not self._recording or self._writer is None:
            return

        # Auto-split: проверить время с начала записи
        elapsed_minutes = (time.monotonic() - self._start_time) / 60.0
        if self._max_minutes > 0 and elapsed_minutes >= self._max_minutes:
            logger.info(
                "RecorderWorker[%d]: auto-split после %.1f мин (%d кадров)",
                self._camera_id,
                elapsed_minutes,
                self._frame_count,
            )
            self._release_writer()
            self._open_writer()
            # Если новый writer не открылся — прервать
            if not self._recording:
                return

        # Resize кадра если размеры не совпадают
        h, w = frame.shape[:2]
        if w != self._width or h != self._height:
            frame = cv2.resize(frame, (self._width, self._height), interpolation=cv2.INTER_LINEAR)

        self._writer.write(frame)
        self._frame_count += 1

    def stop_recording(self) -> dict:
        """Остановить запись и закрыть файл.

        Returns:
            dict со статистикой записи (duration, frame_count, file_path).
        """
        if not self._recording:
            return {"status": "ok", "was_recording": False}

        duration = time.monotonic() - self._start_time
        frames = self._frame_count
        path = self._file_path

        self._release_writer()

        # Размер файла
        file_size_mb = 0.0
        if os.path.exists(path):
            file_size_mb = os.path.getsize(path) / (1024 * 1024)

        logger.info(
            "RecorderWorker[%d]: запись остановлена — %s (%.1fс, %d кадров, %.1f МБ)",
            self._camera_id,
            path,
            duration,
            frames,
            file_size_mb,
        )
        return {
            "status": "ok",
            "was_recording": True,
            "file_path": path,
            "duration_sec": round(duration, 1),
            "frame_count": frames,
            "file_size_mb": round(file_size_mb, 1),
        }

    def _release_writer(self) -> None:
        """Освободить ресурсы VideoWriter."""
        self._recording = False
        if self._writer is not None:
            try:
                self._writer.release()
            except Exception as exc:
                logger.warning(
                    "RecorderWorker[%d]: ошибка при release() — %s",
                    self._camera_id,
                    exc,
                )
            self._writer = None

    @property
    def is_recording(self) -> bool:
        """Активна ли запись."""
        return self._recording

    @property
    def stats(self) -> dict:
        """Статистика текущей записи.

        Returns:
            dict: recording_active, file_path, file_size_mb,
                  duration_sec, frame_count.
        """
        result: dict = {
            "recording_active": self._recording,
            "file_path": self._file_path,
            "frame_count": self._frame_count,
        }

        if self._recording:
            result["duration_sec"] = round(time.monotonic() - self._start_time, 1)

        # Размер файла (безопасно — файл может быть открыт writer'ом)
        if self._file_path and os.path.exists(self._file_path):
            try:
                result["file_size_mb"] = round(os.path.getsize(self._file_path) / (1024 * 1024), 1)
            except OSError:
                result["file_size_mb"] = 0.0
        else:
            result["file_size_mb"] = 0.0

        return result
