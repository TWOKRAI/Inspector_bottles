"""ChainRunnable — последовательный исполнитель цепочки шагов обработки."""
from __future__ import annotations

import time
from typing import Any, Protocol

import numpy as np

from .context import ChainContext
from .error_policy import apply_on_error_policy
from .result import ChainResult, RunnableStep, _collect_side_results, _is_cross_process


class IRunnableChain(Protocol):
    """Протокол исполняемой цепочки обработки.

    ChainRunnable, ParallelChainRunnable, DagRunnable реализуют неявно.
    """

    def execute(
        self,
        frame: np.ndarray,
        metadata: dict[str, Any] | None = None,
    ) -> ChainResult: ...


class ChainRunnable:
    """Последовательная исполняемая цепочка шагов обработки.

    Получает список RunnableStep, поочерёдно применяет операции к кадру.
    Ошибки обрабатываются согласно on_error политике каждого шага.
    """

    def __init__(self, steps: list[RunnableStep]) -> None:
        self._steps = steps

    @property
    def steps(self) -> list[RunnableStep]:
        return list(self._steps)

    def execute(
        self,
        frame: np.ndarray,
        metadata: dict[str, Any] | None = None,
    ) -> ChainResult:
        """Исполнить цепочку последовательно.

        Args:
            frame: Входной кадр (numpy array).
            metadata: Метаданные — camera_id, region_id, seq_id и т.д.

        Returns:
            ChainResult с финальным кадром, детекциями и диагностикой.
        """
        metadata = metadata or {}

        context = ChainContext(
            camera_id=metadata.get("camera_id", ""),
            region_id=metadata.get("region_id", ""),
            seq_id=metadata.get("seq_id", 0),
        )

        result = ChainResult(frame=frame, context=context)
        current_frame = frame
        t_start = time.perf_counter()

        for step in self._steps:
            try:
                if _is_cross_process(step):
                    response = step.execute_remote(
                        frame=current_frame,
                        context=context,
                        input_shm_name=metadata.get("input_shm_name", ""),
                        input_shm_index=metadata.get("input_shm_index", 0),
                    )
                    if getattr(response, "detections", None):
                        result.detections.extend(response.detections)
                    continue

                output = step.operation.execute(current_frame, context)

            except Exception as exc:
                if apply_on_error_policy(step, exc, context, result):
                    break
                continue

            current_frame = output
            _collect_side_results(step.operation, result)

        result.frame = current_frame
        result.processing_time = time.perf_counter() - t_start
        return result


__all__ = ["ChainRunnable", "IRunnableChain"]
