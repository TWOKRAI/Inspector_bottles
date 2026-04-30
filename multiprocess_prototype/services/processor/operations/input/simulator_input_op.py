"""Входная операция захвата кадра через симулятор."""

from __future__ import annotations

from typing import Optional

import numpy as np

from multiprocess_prototype.services.camera.backends import (
    BaseCaptureBackend,
    SimulatorBackend,
)
from multiprocess_prototype.services.processor.operations.base import ChainContext
from multiprocess_prototype.registers.processor.processings.simulator_input_params import (
    SimulatorInputParams,
)


class SimulatorInputOp:
    """Входная операция: генерация кадра через SimulatorBackend.

    Не имеет входных портов — источник данных в DAG.
    Используется в тестах и при разработке без реальных камер.
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
        """Создать SimulatorBackend с применением дефолтов из схемы."""
        defaults = SimulatorInputParams().model_dump()
        p = {**defaults, **self._params}
        return SimulatorBackend(
            width=int(p["width"]),
            height=int(p["height"]),
            image_path=p.get("image_path"),
        )

    def execute_dag(self, inputs: dict, context: ChainContext) -> dict[str, np.ndarray | None]:
        """Захватить (сгенерировать) кадр. Входные порты игнорируются (источник DAG)."""
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


__all__ = ["SimulatorInputOp"]
