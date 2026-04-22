"""Параллельный executor цепочки обработки (Phase 5b).

Бандлы исполняются последовательно (barrier между уровнями),
шаги внутри бандла — параллельно через ChainThreadPool.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np

from services.processor.chain.runnable import (
    ChainResult,
    RunnableStep,
    _collect_side_results,
)
from services.processor.chain.thread_pool import ChainThreadPool
from services.processor.operations.base import ChainContext

logger = logging.getLogger(__name__)


class ParallelChainRunnable:
    """Исполняемая цепочка с параллельными бандлами.

    Бандлы исполняются последовательно (barrier), шаги внутри бандла — параллельно.
    Один step в бандле → синхронное исполнение (без overhead пула).
    """

    def __init__(
        self,
        bundles: list[list[RunnableStep]],
        pool: ChainThreadPool,
    ) -> None:
        self._bundles = bundles
        self._pool = pool

    @property
    def steps(self) -> list[RunnableStep]:
        """Flattened список всех steps (для совместимости с ChainRunnable interface)."""
        return [step for bundle in self._bundles for step in bundle]

    def execute(
        self,
        frame: np.ndarray,
        metadata: dict[str, Any] | None = None,
    ) -> ChainResult:
        """Исполнить цепочку с параллельными бандлами.

        Для каждого бандла последовательно:
        1. Bundle из 1 step — синхронное исполнение (без overhead пула).
        2. Bundle из 2+ steps — submit_bundle → collect_results.
        3. Merge результатов: side results (detections/masks/contours) со всех steps.
        4. Error handling по on_error политике каждого шага.
        5. current_frame передаётся в следующий бандл.

        Args:
            frame: Входной кадр (numpy array, BGR).
            metadata: Метаданные — camera_id, region_id, seq_id и т.д.

        Returns:
            ChainResult с финальным кадром, детекциями и диагностикой.
        """
        metadata = metadata or {}

        # Инициализация контекста из metadata
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
                # Один шаг — синхронно (без overhead пула)
                current_frame, should_break = self._execute_single(
                    bundle[0], current_frame, context, result,
                )
                if should_break:
                    break
            else:
                # Параллельный бандл — через пул потоков
                current_frame, should_break = self._execute_parallel(
                    bundle, current_frame, context, result,
                )
                if should_break:
                    break

        result.frame = current_frame
        result.processing_time = time.perf_counter() - t_start
        return result

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _execute_single(
        self,
        step: RunnableStep,
        current_frame: np.ndarray,
        context: ChainContext,
        result: ChainResult,
    ) -> tuple[np.ndarray, bool]:
        """Синхронное исполнение одного шага.

        Returns:
            (current_frame, should_break) — обновлённый кадр и флаг прерывания.
        """
        try:
            output = step.operation.execute(current_frame, context)
        except Exception as exc:
            return self._handle_step_error(step, exc, current_frame, context, result)

        # Успех — собираем побочные результаты
        _collect_side_results(step.operation, result)
        return output, False

    def _execute_parallel(
        self,
        bundle: list[RunnableStep],
        current_frame: np.ndarray,
        context: ChainContext,
        result: ChainResult,
    ) -> tuple[np.ndarray, bool]:
        """Параллельное исполнение бандла через ChainThreadPool.

        Returns:
            (current_frame, should_break) — обновлённый кадр и флаг прерывания.
        """
        futures = self._pool.submit_bundle(bundle, current_frame, context)
        results_list = self._pool.collect_results(futures, bundle)

        should_break = False
        first_successful_frame: np.ndarray | None = None

        for step, res in results_list:
            if isinstance(res, Exception):
                # Ошибка или timeout — обработка по on_error политике
                _, step_break = self._handle_step_error(
                    step, res, current_frame, context, result,
                )
                if step_break:
                    should_break = True
            else:
                # Успех — собрать side results от операции
                _collect_side_results(step.operation, result)
                # Запоминаем frame от первого успешного step
                if first_successful_frame is None:
                    first_successful_frame = res

        if should_break:
            return current_frame, True

        # Frame от первого успешного step (параллельные steps независимы —
        # каждый получил копию кадра). Если нет успешных — оставляем текущий.
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
        """Обработать ошибку шага согласно on_error политике.

        Returns:
            (current_frame, should_break) — кадр без изменений и флаг прерывания.
        """
        if step.on_error == "skip":
            msg = (
                f"Операция '{step.node.operation_ref}' "
                f"(node={step.node.node_id}) упала с ошибкой: {exc}. "
                f"on_error=skip — пропускаем."
            )
            logger.warning(msg)
            context.warnings.append(msg)
            result.skipped_nodes.append(step.node.node_id)
            return current_frame, False

        elif step.on_error == "fail_region":
            msg = (
                f"Операция '{step.node.operation_ref}' "
                f"(node={step.node.node_id}) упала с ошибкой: {exc}. "
                f"on_error=fail_region — прерываем цепочку."
            )
            logger.error(msg)
            context.errors.append(msg)
            result.failed = True
            result.fail_level = "region"
            return current_frame, True

        else:
            # on_error == "fail_camera" или неизвестное значение
            msg = (
                f"Операция '{step.node.operation_ref}' "
                f"(node={step.node.node_id}) упала с ошибкой: {exc}. "
                f"on_error={step.on_error} — прерываем цепочку (camera)."
            )
            logger.error(msg)
            context.errors.append(msg)
            result.failed = True
            result.fail_level = "camera"
            return current_frame, True


__all__ = ["ParallelChainRunnable"]
