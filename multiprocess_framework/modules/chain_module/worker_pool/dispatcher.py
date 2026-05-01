"""WorkerPoolDispatcher — маршрутизация задач в worker pool.

Живёт внутри Processor-процесса. Round-robin распределение по worker-процессам
через IPC+SHM. Блокирует вызывающий поток до получения ответа или timeout.
Thread-safe: dispatch() может вызываться из разных потоков (ChainThreadPool).
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .protocol import WorkerTaskRequest, WorkerTaskResponse


@dataclass
class PendingTask:
    """Ожидающая задача: Event для блокировки + слот для ответа."""

    event: threading.Event = field(default_factory=threading.Event)
    response: WorkerTaskResponse | None = None


class WorkerPoolDispatcher:
    """Диспетчер задач для worker pool.

    Round-robin маршрутизация по worker-процессам.
    Backpressure: при переполнении — drop oldest (отменяем самую старую задачу).
    Timeout: если worker не ответил вовремя — возвращаем error response.

    Args:
        send_fn: Callable для отправки IPC-сообщения.
            Сигнатура: send_fn(target: str, data: dict, data_type: str) -> bool
        worker_count: Количество worker-процессов.
        timeout: Максимальное время ожидания ответа (секунды).
        input_queue_size: Максимальное количество одновременно ожидающих задач.
    """

    def __init__(
        self,
        send_fn: Callable,
        worker_count: int,
        timeout: float = 5.0,
        input_queue_size: int = 4,
        logger: Any = None,
    ) -> None:
        self._send_fn = send_fn
        self._timeout = timeout
        self._input_queue_size = max(1, input_queue_size)
        self._log = logger

        self._worker_names: list[str] = [
            f"processor_worker_{i}" for i in range(worker_count)
        ]

        self._lock = threading.Lock()
        self._pending: dict[str, PendingTask] = {}
        self._next_worker: int = 0

        self._drops_total: int = 0
        self._dispatched_total: int = 0
        self._timeout_total: int = 0

    def dispatch(
        self,
        operation_ref: str,
        params: dict,
        camera_id: str,
        region_id: str,
        seq_id: int,
        input_shm_name: str,
        input_shm_index: int,
        frame_shape: tuple,
    ) -> WorkerTaskResponse:
        """Отправить задачу в worker pool и дождаться ответа.

        Блокирует вызывающий поток до получения ответа или timeout.
        При переполнении очереди — drop oldest.

        Returns:
            WorkerTaskResponse с результатом или ошибкой.
        """
        request = WorkerTaskRequest.create(
            camera_id=camera_id,
            region_id=region_id,
            seq_id=seq_id,
            operation_ref=operation_ref,
            params=params,
            input_shm_name=input_shm_name,
            input_shm_index=input_shm_index,
            frame_shape=frame_shape,
        )

        pending = PendingTask()

        with self._lock:
            self._enforce_backpressure()
            worker_name = self._worker_names[self._next_worker]
            self._next_worker = (self._next_worker + 1) % len(self._worker_names)
            self._pending[request.task_id] = pending
            self._dispatched_total += 1

        self._send_fn(
            target=worker_name,
            data=request.to_dict(),
            data_type="worker_task_request",
        )

        if self._log is not None:
            self._log._log_debug(
                f"Задача {request.task_id} отправлена worker={worker_name}, operation={operation_ref}"
            )

        signaled = pending.event.wait(timeout=self._timeout)

        if not signaled:
            with self._lock:
                self._pending.pop(request.task_id, None)
                self._timeout_total += 1

            if self._log is not None:
                self._log._log_warning(
                    f"Timeout задачи {request.task_id} ({self._timeout:.1f}s), operation={operation_ref}"
                )
            return WorkerTaskResponse.error_response(
                task_id=request.task_id,
                error="timeout",
            )

        with self._lock:
            self._pending.pop(request.task_id, None)

        if pending.response is not None:
            return pending.response

        return WorkerTaskResponse.error_response(
            task_id=request.task_id,
            error="internal: response lost",
        )

    def handle_response(self, response_dict: dict) -> None:
        """Обработать ответ от worker-процесса.

        Парсит WorkerTaskResponse, находит pending задачу по task_id,
        записывает ответ и сигнализирует Event.
        """
        response = WorkerTaskResponse.from_dict(response_dict)

        with self._lock:
            pending = self._pending.get(response.task_id)

        if pending is None:
            if self._log is not None:
                self._log._log_warning(
                    f"Late response для task_id={response.task_id} (нет в pending), игнорируем"
                )
            return

        pending.response = response
        pending.event.set()

        if self._log is not None:
            self._log._log_debug(
                f"Ответ получен для task_id={response.task_id},"
                f" success={response.success}, time={response.processing_time:.3f}s"
            )

    def _enforce_backpressure(self) -> None:
        """Drop oldest: если pending >= input_queue_size, удалить самую старую задачу.

        Вызывается под self._lock.
        """
        while len(self._pending) >= self._input_queue_size:
            oldest_task_id = next(iter(self._pending))
            oldest = self._pending.pop(oldest_task_id)
            self._drops_total += 1

            if self._log is not None:
                self._log._log_warning(
                    f"Backpressure: drop task_id={oldest_task_id}"
                    f" (pending={len(self._pending) + 1} >= limit={self._input_queue_size})"
                )

            oldest.response = WorkerTaskResponse.error_response(
                task_id=oldest_task_id,
                error="dropped: backpressure overflow",
            )
            oldest.event.set()

    @property
    def stats(self) -> dict:
        """Статистика диспетчера для мониторинга."""
        with self._lock:
            return {
                "pending": len(self._pending),
                "drops_total": self._drops_total,
                "dispatched_total": self._dispatched_total,
                "timeout_total": self._timeout_total,
            }


__all__ = ["WorkerPoolDispatcher", "PendingTask"]
