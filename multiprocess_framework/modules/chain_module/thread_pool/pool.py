"""ChainThreadPool — обёртка над ThreadPoolExecutor для параллельного исполнения шагов."""
from __future__ import annotations

import concurrent.futures
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

import numpy as np

from ...base_manager import BaseManager, ObservableMixin


class ChainThreadPool(BaseManager, ObservableMixin):
    """Обёртка над ThreadPoolExecutor с timeout и graceful shutdown.

    Args:
        max_workers: Количество рабочих потоков.
        step_timeout: Максимальное время ожидания одного шага (секунды).
        logger: LoggerManager или любой ObservableMixin-совместимый объект.
    """

    def __init__(
        self,
        max_workers: int = 2,
        step_timeout: float = 10.0,
        logger: Any = None,
    ) -> None:
        BaseManager.__init__(self, manager_name="ChainThreadPool")
        ObservableMixin.__init__(self, managers={"logger": logger})
        self._max_workers = max_workers
        self._step_timeout = step_timeout
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._lock = threading.Lock()

    def initialize(self) -> bool:
        self.is_initialized = True
        return True

    def shutdown(self) -> bool:
        self._executor.shutdown(wait=True)
        self.is_initialized = False
        return True

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
                self._log_warning(
                    f"Операция '{step.node.operation_ref}' (node={step.node.node_id})"
                    f" превысила timeout {actual_timeout}s"
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


__all__ = ["ChainThreadPool"]
