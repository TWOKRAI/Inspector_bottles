"""ParallelChainRunnable — параллельный исполнитель цепочки обработки.

Бандлы исполняются последовательно (barrier между уровнями),
шаги внутри бандла — параллельно через ChainThreadPool.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np

from .context import ChainContext
from .result import ChainResult, RunnableStep, _collect_side_results

logger = logging.getLogger(__name__)


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
            if len(bundle) == 1:
                current_frame, should_break = self._execute_single(
                    bundle[0], current_frame, context, result,
                )
            else:
                current_frame, should_break = self._execute_parallel(
                    bundle, current_frame, context, result,
                )
            if should_break:
                break

        result.frame = current_frame
        result.processing_time = time.perf_counter() - t_start
        return result

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
            return self._handle_step_error(step, exc, current_frame, context, result)

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
                _, step_break = self._handle_step_error(
                    step, res, current_frame, context, result,
                )
                if step_break:
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

    @staticmethod
    def _handle_step_error(
        step: RunnableStep,
        exc: Exception,
        current_frame: np.ndarray,
        context: ChainContext,
        result: ChainResult,
    ) -> tuple[np.ndarray, bool]:
        if step.on_error == "skip":
            msg = (
                f"Операция '{step.node.operation_ref}' "
                f"(node={step.node.node_id}) упала: {exc}. on_error=skip."
            )
            logger.warning(msg)
            context.warnings.append(msg)
            result.skipped_nodes.append(step.node.node_id)
            return current_frame, False

        elif step.on_error == "fail_region":
            msg = (
                f"Операция '{step.node.operation_ref}' "
                f"(node={step.node.node_id}) упала: {exc}. on_error=fail_region."
            )
            logger.error(msg)
            context.errors.append(msg)
            result.failed = True
            result.fail_level = "region"
            return current_frame, True

        else:
            msg = (
                f"Операция '{step.node.operation_ref}' "
                f"(node={step.node.node_id}) упала: {exc}. "
                f"on_error={step.on_error} (camera)."
            )
            logger.error(msg)
            context.errors.append(msg)
            result.failed = True
            result.fail_level = "camera"
            return current_frame, True


__all__ = ["ParallelChainRunnable"]
