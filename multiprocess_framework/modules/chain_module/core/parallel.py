"""ParallelChainRunnable — параллельный исполнитель цепочки обработки.

Бандлы исполняются последовательно (barrier между уровнями),
шаги внутри бандла — параллельно через ChainThreadPool.

Cross-process шаги (реализующие IRemoteExecutable) обрабатываются
синхронно через ``execute_remote``: dispatcher уже сам блокирует
поток в ожидании ответа от worker-процесса, параллелизм через
ThreadPool не даёт выигрыша.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np

from .context import ChainContext
from .error_policy import apply_on_error_policy
from .result import ChainResult, RunnableStep, _collect_side_results, _is_cross_process


class ParallelChainRunnable:
    """Исполняемая цепочка с параллельными бандлами.

    Бандлы исполняются последовательно, шаги внутри бандла — параллельно.
    Один шаг в бандле → синхронное исполнение (без overhead пула).
    """

    def __init__(
        self,
        bundles: list[list[RunnableStep]],
        pool: Any,  # ChainThreadPool — импортируем через Any для избежания цикла
    ) -> None:
        self._bundles = bundles
        self._pool = pool

    @property
    def steps(self) -> list[RunnableStep]:
        return [step for bundle in self._bundles for step in bundle]

    def execute(
        self,
        frame: np.ndarray,
        metadata: dict[str, Any] | None = None,
    ) -> ChainResult:
        """Исполнить цепочку с параллельными бандлами.

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

        for bundle in self._bundles:
            remote_steps = [s for s in bundle if _is_cross_process(s)]
            local_steps = [s for s in bundle if not _is_cross_process(s)]

            should_break = False
            for step in remote_steps:
                step_break = self._execute_remote(step, current_frame, metadata, context, result)
                if step_break:
                    should_break = True
                    break
            if should_break:
                break

            if not local_steps:
                continue

            if len(local_steps) == 1:
                current_frame, should_break = self._execute_single(
                    local_steps[0], current_frame, context, result,
                )
            else:
                current_frame, should_break = self._execute_parallel(
                    local_steps, current_frame, context, result,
                )
            if should_break:
                break

        result.frame = current_frame
        result.processing_time = time.perf_counter() - t_start
        return result

    def _execute_remote(
        self,
        step: Any,  # RunnableStep | IRemoteExecutable proxy (CrossProcessStep)
        current_frame: np.ndarray,
        metadata: dict[str, Any],
        context: ChainContext,
        result: ChainResult,
    ) -> bool:
        """Cross-process шаг: вызвать execute_remote, собрать детекции.

        Frame не модифицируется (как в ChainRunnable / DagRunnable).
        Возвращает should_break.
        """
        try:
            response = step.execute_remote(
                frame=current_frame,
                context=context,
                input_shm_name=metadata.get("input_shm_name", ""),
                input_shm_index=metadata.get("input_shm_index", 0),
            )
        except Exception as exc:
            return apply_on_error_policy(step, exc, context, result)

        if getattr(response, "detections", None):
            result.detections.extend(response.detections)
        return False

    def _execute_single(
        self,
        step: RunnableStep,
        current_frame: np.ndarray,
        context: ChainContext,
        result: ChainResult,
    ) -> tuple[np.ndarray, bool]:
        try:
            output = step.operation.execute(current_frame, context)
        except Exception as exc:
            should_break = apply_on_error_policy(step, exc, context, result)
            return current_frame, should_break

        _collect_side_results(step.operation, result)
        return output, False

    def _execute_parallel(
        self,
        bundle: list[RunnableStep],
        current_frame: np.ndarray,
        context: ChainContext,
        result: ChainResult,
    ) -> tuple[np.ndarray, bool]:
        futures = self._pool.submit_bundle(bundle, current_frame, context)
        results_list = self._pool.collect_results(futures, bundle)

        should_break = False
        first_successful_frame: np.ndarray | None = None

        for step, res in results_list:
            if isinstance(res, Exception):
                if isinstance(res, TimeoutError):
                    context.timeouts.append(step.node.node_id)
                if apply_on_error_policy(step, res, context, result):
                    should_break = True
            else:
                _collect_side_results(step.operation, result)
                if first_successful_frame is None:
                    first_successful_frame = res

        if should_break:
            return current_frame, True

        if first_successful_frame is not None:
            current_frame = first_successful_frame

        return current_frame, False


__all__ = ["ParallelChainRunnable"]
