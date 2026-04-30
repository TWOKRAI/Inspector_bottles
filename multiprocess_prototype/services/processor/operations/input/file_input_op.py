"""Входная операция захвата кадра из видеофайла."""

from __future__ import annotations

from typing import Optional

import numpy as np

from multiprocess_prototype.services.camera.backends import (
    BaseCaptureBackend,
    FileSourceBackend,
)
from multiprocess_prototype.services.processor.operations.base import ChainContext


class FileInputOp:
    """Входная операция: чтение кадров из видеофайла с зацикливанием (loop).

    Не имеет входных портов — источник данных в DAG.
    Backend создаётся лениво при первом вызове execute_dag().

    Raises:
        ValueError: если file_path не задан при попытке старта.
    """

    def __init__(self) -> None:
        self._params: dict = {}
        self._backend: Optional[BaseCaptureBackend] = None
        self._started: bool = False

    def configure(self, params: dict) -> None:
        """Применить параметры. Если backend уже создан и параметры изменились — пересоздаём."""
        if self._backend is not None and params != self._params:
            self.close()
        self._params = dict(params)

    def _ensure_started(self) -> None:
        """Запустить backend если ещё не запущен.

        Raises:
            ValueError: если file_path не задан или пустой.
        """
        if self._started:
            return
        file_path = self._params.get("file_path", "")
        if not file_path:
            raise ValueError("FileInput: не указан file_path")
        self._backend = FileSourceBackend(file_path)
        self._backend.start()
        self._started = True

    def execute_dag(self, inputs: dict, context: ChainContext) -> dict[str, np.ndarray | None]:
        """Захватить кадр из файла. Входные порты игнорируются (источник DAG)."""
        self._ensure_started()
        frame = self._backend.capture_frame() if self._backend else None
        return {"out": frame}

    def execute(self, frame: np.ndarray, context: ChainContext) -> np.ndarray:
        """Protocol-fallback: делегирует в execute_dag."""
        result = self.execute_dag({}, context)
        return result["out"]

    def close(self) -> None:
        """Закрыть backend и сбросить состояние."""
        if self._backend is not None:
            self._backend.close()
        self._backend = None
        self._started = False


__all__ = ["FileInputOp"]
