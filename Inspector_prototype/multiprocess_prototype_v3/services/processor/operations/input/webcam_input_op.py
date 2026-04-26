"""Входная операция захвата кадра с веб-камеры."""

from __future__ import annotations

from typing import Optional

import numpy as np

from multiprocess_prototype_v3.services.camera.backends import (
    BaseCaptureBackend,
    WebcamBackend,
)
from multiprocess_prototype_v3.services.processor.operations.base import ChainContext
from multiprocess_prototype_v3.registers.processor.processings.webcam_input_params import (
    WebcamInputParams,
)


class WebcamInputOp:
    """Входная операция: захват кадра с веб-камеры через OpenCV.

    Не имеет входных портов — источник данных в DAG.
    Backend создаётся лениво при первом вызове execute_dag().
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
        """Запустить backend если ещё не запущен."""
        if self._started:
            return
        self._backend = self._create_backend()
        self._backend.start()
        self._started = True

    def _create_backend(self) -> BaseCaptureBackend:
        """Создать WebcamBackend с применением дефолтов из схемы."""
        defaults = WebcamInputParams().model_dump()
        p = {**defaults, **self._params}
        return WebcamBackend(
            width=int(p["width"]),
            height=int(p["height"]),
            device_id=int(p.get("device_id", 0)),
        )

    def execute_dag(self, inputs: dict, context: ChainContext) -> dict[str, np.ndarray | None]:
        """Захватить кадр. Входные порты игнорируются (источник DAG)."""
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


__all__ = ["WebcamInputOp"]
