"""ChainThreadPool — обёртка над ThreadPoolExecutor для параллельного исполнения шагов."""
from __future__ import annotations

import concurrent.futures
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class ChainThreadPool:
    """Обёртка над ThreadPoolExecutor с timeout и graceful shutdown.

    Args:
        max_workers: Количество рабочих потоков.
        step_timeout: Максимальное время ожидания одного шага (секунды).
    """

    def __init__(self, max_workers: int = 2, step_timeout: float = 10.0) -> None:
        self._max_workers = max_workers
        self._step_timeout = step_timeout
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._lock = threading.Lock()

    @property
    def max_workers(self) -> int:
        return self._max_workers

    @property
    def step_timeout(self) -> float:
        return self._step_timeout

    def submit_bundle(
        self,
        steps: list[Any],  # list[RunnableStep]
        frame: np.ndarray,
        context: Any,  # ChainContext
    ) -> list[Future]:
        """Отправить шаги бандла на параллельное исполнение.

        Каждый шаг получает frame.copy() для thread-safety.
        """
        futures: list[Future] = []
        for step in steps:
            f = self._executor.submit(step.operation.execute, frame.copy(), context)
            futures.append(f)
        return futures

    def collect_results(
        self,
        futures: list[Future],
        steps: list[Any],  # list[RunnableStep]
        timeout: float | None = None,
    ) -> list[tuple[Any, np.ndarray | Exception]]:
        """Дождаться результатов всех futures.

        Зависшие задачи (превысившие timeout) отменяются → TimeoutError.
        """
        actual_timeout = timeout if timeout is not None else self._step_timeout

        done, not_done = concurrent.futures.wait(futures, timeout=actual_timeout)

        results: list[tuple[Any, np.ndarray | Exception]] = []

        for fut, step in zip(futures, steps):
            if fut in done:
                try:
                    results.append((step, fut.result()))
                except Exception as exc:
                    results.append((step, exc))
            else:
                logger.warning(
                    "Операция '%s' (node=%s) превысила timeout %ss",
                    step.node.operation_ref,
                    step.node.node_id,
                    actual_timeout,
                )
                fut.cancel()
                results.append(
                    (
                        step,
                        TimeoutError(
                            f"Timeout {actual_timeout}s для {step.node.operation_ref}"
                        ),
                    )
                )

        return results

    def resize(self, max_workers: int) -> None:
        """Пересоздать executor с новым размером пула (thread-safe)."""
        with self._lock:
            self._executor.shutdown(wait=True)
            self._max_workers = max_workers
            self._executor = ThreadPoolExecutor(max_workers=max_workers)

    def shutdown(self, wait: bool = True) -> None:
        """Graceful shutdown пула потоков."""
        self._executor.shutdown(wait=wait)


__all__ = ["ChainThreadPool"]
