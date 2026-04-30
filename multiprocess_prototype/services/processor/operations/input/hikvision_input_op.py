"""Входная операция захвата кадра с камеры Hikvision."""

from __future__ import annotations

from typing import Optional

import numpy as np

from multiprocess_prototype.services.camera.backends import (
    BaseCaptureBackend,
    CameraBackendParams,
    SimulatorBackend,
    create_camera_backend,
)
from multiprocess_prototype.services.processor.operations.base import ChainContext
from multiprocess_prototype.registers.processor.processings.hikvision_input_params import (
    HikvisionInputParams,
)


class HikvisionInputOp:
    """Входная операция: захват кадра с камеры Hikvision.

    Не имеет входных портов — источник данных в DAG.
    Использует фабрику create_camera_backend("hikvision", ...) для создания backend.
    На не-Windows автоматически использует SimulatorBackend как fallback.
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
        """Создать backend через фабрику create_camera_backend.

        На не-Windows фабрика автоматически возвращает SimulatorBackend.
        """
        defaults = HikvisionInputParams().model_dump()
        p = {**defaults, **self._params}
        backend_params = CameraBackendParams(
            width=int(p.get("target_width", 1920)),
            height=int(p.get("target_height", 1080)),
            device_id=0,
            camera_index=int(p.get("camera_index", 0)),
            hikvision_width=int(p.get("target_width", 1920)),
            hikvision_height=int(p.get("target_height", 1080)),
            simulator_image_path=None,
            send_to_gui=lambda topic, data: None,
        )
        return create_camera_backend("hikvision", backend_params)

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


__all__ = ["HikvisionInputOp"]
