"""Управление пулом потоков для параллельного исполнения шагов chain (Phase 5b)."""

from __future__ import annotations

import concurrent.futures
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor

import numpy as np

from services.processor.chain.runnable import RunnableStep
from services.processor.operations.base import ChainContext

logger = logging.getLogger(__name__)


class ChainThreadPool:
    """Обёртка над ThreadPoolExecutor с настраиваемым размером, timeout и graceful shutdown."""

    def __init__(self, max_workers: int = 2, step_timeout: float = 10.0) -> None:
        self._max_workers = max_workers
        self._step_timeout = step_timeout
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._lock = threading.Lock()  # для resize

    @property
    def max_workers(self) -> int:
        """Текущий размер пула потоков."""
        return self._max_workers

    @property
    def step_timeout(self) -> float:
        """Timeout ожидания результата одного шага (секунды)."""
        return self._step_timeout

    def submit_bundle(
        self,
        steps: list[RunnableStep],
        frame: np.ndarray,
        context: ChainContext,
    ) -> list[Future]:
        """Отправить все steps bundle на исполнение.

        Каждый step получает frame.copy() для thread safety —
        операции не должны модифицировать общий массив.

        Args:
            steps: Список шагов для параллельного выполнения.
            frame: Входной кадр (будет скопирован для каждого шага).
            context: Контекст цепочки (общий, read-only использование).

        Returns:
            Список Future в том же порядке, что и steps.
        """
        futures: list[Future] = []
        for step in steps:
            # frame.copy() — каждый поток работает с независимой копией кадра
            f = self._executor.submit(step.operation.execute, frame.copy(), context)
            futures.append(f)
        return futures

    def collect_results(
        self,
        futures: list[Future],
        steps: list[RunnableStep],
        timeout: float | None = None,
    ) -> list[tuple[RunnableStep, np.ndarray | Exception]]:
        """Дождаться результатов всех futures.

        Зависшие задачи (превысившие timeout) логируются как WARNING,
        отменяются и возвращают TimeoutError.

        Args:
            futures: Список Future, полученных из submit_bundle.
            steps: Список шагов — должен соответствовать futures по индексам.
            timeout: Переопределить timeout (если None — используется step_timeout).

        Returns:
            Список пар (step, result_or_exception) в том же порядке.
        """
        actual_timeout = timeout if timeout is not None else self._step_timeout

        # Ждём все futures с общим timeout
        done, not_done = concurrent.futures.wait(futures, timeout=actual_timeout)

        results: list[tuple[RunnableStep, np.ndarray | Exception]] = []

        for fut, step in zip(futures, steps):
            if fut in done:
                try:
                    # Успешное завершение — берём результат
                    results.append((step, fut.result()))
                except Exception as exc:
                    # Операция завершилась с исключением
                    results.append((step, exc))
            else:
                # Задача не успела выполниться за timeout
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
        """Пересоздать executor с новым размером пула.

        Thread-safe через lock: дожидается завершения текущих задач,
        затем создаёт новый ThreadPoolExecutor.

        Args:
            max_workers: Новое количество рабочих потоков.
        """
        with self._lock:
            # Ждём завершения всех запущенных задач перед пересозданием
            self._executor.shutdown(wait=True)
            self._max_workers = max_workers
            self._executor = ThreadPoolExecutor(max_workers=max_workers)

    def shutdown(self, wait: bool = True) -> None:
        """Graceful shutdown пула потоков.

        Args:
            wait: Если True — дождаться завершения всех запущенных задач.
        """
        self._executor.shutdown(wait=wait)


__all__ = ["ChainThreadPool"]
