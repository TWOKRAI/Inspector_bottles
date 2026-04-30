"""WorkerPoolDispatcher — маршрутизация задач в worker pool (Phase 5c).

Живёт внутри Processor-процесса. Отправляет тяжёлые шаги обработки
в отдельные worker-процессы через IPC+SHM. Блокирует вызывающий поток
до получения ответа или timeout.

Thread-safe: dispatch() может вызываться из разных потоков (ThreadPool Phase 5b).
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from services.processor.worker_pool.protocol import (
    WorkerTaskRequest,
    WorkerTaskResponse,
)

logger = logging.getLogger(__name__)


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
    ) -> None:
        self._send_fn = send_fn
        self._timeout = timeout
        self._input_queue_size = max(1, input_queue_size)

        # Имена worker-процессов для round-robin маршрутизации
        self._worker_names: list[str] = [
            f"processor_worker_{i}" for i in range(worker_count)
        ]

        # Потокобезопасное состояние
        self._lock = threading.Lock()
        self._pending: dict[str, PendingTask] = {}
        self._next_worker: int = 0

        # Счётчики для мониторинга
        self._drops_total: int = 0
        self._dispatched_total: int = 0
        self._timeout_total: int = 0

        # Метрики времени dispatch (running average)
        self._dispatch_time_sum_ms: float = 0.0
        self._dispatch_time_count: int = 0

        # Временные метки отправки задач: task_id → monotonic time
        self._sent_at: dict[str, float] = {}

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
        При переполнении очереди — drop oldest (самая старая задача получает error).

        Returns:
            WorkerTaskResponse с результатом или ошибкой.
        """
        # Создаём request с уникальным task_id
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
            # Backpressure: drop oldest если очередь заполнена
            self._enforce_backpressure()

            # Выбираем worker round-robin
            worker_name = self._worker_names[self._next_worker]
            self._next_worker = (self._next_worker + 1) % len(self._worker_names)

            # Регистрируем pending task
            self._pending[request.task_id] = pending
            self._dispatched_total += 1

        # Отправляем IPC (вне lock — send_fn может блокировать)
        self._send_fn(
            target=worker_name,
            data=request.to_dict(),
            data_type="worker_task_request",
        )

        logger.debug(
            "Задача %s отправлена worker=%s, operation=%s",
            request.task_id,
            worker_name,
            operation_ref,
        )

        # Ожидаем ответ или timeout
        signaled = pending.event.wait(timeout=self._timeout)

        if not signaled:
            # Timeout — удаляем из pending и возвращаем ошибку
            with self._lock:
                self._pending.pop(request.task_id, None)
                self._timeout_total += 1

            logger.warning(
                "Timeout задачи %s (%.1fs), operation=%s",
                request.task_id,
                self._timeout,
                operation_ref,
            )
            return WorkerTaskResponse.error_response(
                task_id=request.task_id,
                error="timeout",
            )

        # Ответ получен — забираем из pending (может уже не быть, если drop/handle убрали)
        with self._lock:
            self._pending.pop(request.task_id, None)

        # Используем локальный pending — он всегда содержит response,
        # независимо от того, кто разблокировал (handle_response или backpressure)
        if pending.response is not None:
            return pending.response

        # Не должно произойти, но на всякий случай
        return WorkerTaskResponse.error_response(
            task_id=request.task_id,
            error="internal: response lost",
        )

    def handle_response(self, response_dict: dict) -> None:
        """Обработать ответ от worker-процесса.

        Парсит WorkerTaskResponse, находит pending задачу по task_id,
        записывает ответ и сигнализирует Event.

        Если task_id не найден в pending (late response) — игнорируем с WARN.
        """
        response = WorkerTaskResponse.from_dict(response_dict)

        with self._lock:
            pending = self._pending.get(response.task_id)

        if pending is None:
            logger.warning(
                "Late response для task_id=%s (нет в pending), игнорируем",
                response.task_id,
            )
            return

        # Записываем ответ и сигнализируем ожидающий поток
        pending.response = response
        pending.event.set()

        logger.debug(
            "Ответ получен для task_id=%s, success=%s, time=%.3fs",
            response.task_id,
            response.success,
            response.processing_time,
        )

    def _enforce_backpressure(self) -> None:
        """Drop oldest: если pending >= input_queue_size, удалить самую старую задачу.

        Вызывается под self._lock.
        """
        while len(self._pending) >= self._input_queue_size:
            # dict сохраняет порядок вставки (Python 3.7+) — первый ключ = самый старый
            oldest_task_id = next(iter(self._pending))
            oldest = self._pending.pop(oldest_task_id)

            self._drops_total += 1

            logger.warning(
                "Backpressure: drop task_id=%s (pending=%d >= limit=%d)",
                oldest_task_id,
                len(self._pending) + 1,
                self._input_queue_size,
            )

            # Разблокируем ожидающий поток с error response
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


__all__ = ["WorkerPoolDispatcher"]
