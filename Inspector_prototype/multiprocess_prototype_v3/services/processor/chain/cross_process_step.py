"""Обёртка для шага, исполняемого в отдельном worker-процессе (Phase 5c).

CrossProcessStep проксирует все атрибуты обычного RunnableStep,
но при вызове execute_remote() отправляет задачу через WorkerPoolDispatcher
вместо локального исполнения.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from services.processor.operations.base import ChainContext
from services.processor.worker_pool.dispatcher import WorkerPoolDispatcher
from services.processor.worker_pool.protocol import WorkerTaskResponse

from .runnable import RunnableStep

logger = logging.getLogger(__name__)


class CrossProcessStep:
    """Обёртка для шага, который исполняется в отдельном worker-процессе.

    Проксирует атрибуты RunnableStep (node, operation, on_error)
    через __getattr__, чтобы код обработки ошибок и сбора результатов
    работал единообразно с обычными шагами.
    """

    def __init__(self, step: RunnableStep, dispatcher: WorkerPoolDispatcher) -> None:
        # Сохраняем напрямую в __dict__, чтобы не срабатывал __getattr__
        self.__dict__["step"] = step
        self.__dict__["dispatcher"] = dispatcher

    def __getattr__(self, name: str) -> Any:
        """Проксируем атрибуты к внутреннему step (node, operation, on_error и т.д.)."""
        return getattr(self.step, name)

    def execute_remote(
        self,
        frame: np.ndarray,
        context: ChainContext,
        input_shm_name: str,
        input_shm_index: int,
    ) -> WorkerTaskResponse:
        """Отправить шаг на обработку в worker pool.

        Блокирует вызывающий поток до получения ответа или timeout
        (поведение WorkerPoolDispatcher.dispatch).

        Args:
            frame: Входной кадр — используется только для получения shape.
            context: Контекст цепочки (camera_id, region_id, seq_id).
            input_shm_name: Имя SHM-блока с входным кадром.
            input_shm_index: Индекс в SHM-блоке.

        Returns:
            WorkerTaskResponse с результатом обработки.

        Raises:
            RuntimeError: Если worker вернул ошибку (success=False).
        """
        response = self.dispatcher.dispatch(
            operation_ref=self.step.node.operation_ref,
            params=self.step.node.params,
            camera_id=context.camera_id,
            region_id=context.region_id,
            seq_id=context.seq_id,
            input_shm_name=input_shm_name,
            input_shm_index=input_shm_index,
            frame_shape=tuple(frame.shape),
        )

        if not response.success:
            raise RuntimeError(
                f"Worker pool error для операции "
                f"'{self.step.node.operation_ref}': {response.error}"
            )

        return response


__all__ = ["CrossProcessStep"]
