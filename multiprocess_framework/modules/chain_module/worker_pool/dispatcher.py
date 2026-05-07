"""WorkerPoolDispatcher — маршрутизация задач в worker pool.

Живёт внутри Processor-процесса. Round-robin распределение по worker-процессам
через IPC+SHM. Блокирует вызывающий поток до получения ответа или timeout.
Thread-safe: dispatch() может вызываться из разных потоков (ChainThreadPool).

Интегрирован с ``BaseManager + ObservableMixin``:
    - ``logger``  → структурное логирование (``self._log_*``)
    - ``stats``   → метрики (``self._record_metric`` / ``self._record_timing``)
    - ``errors``  → трекинг ошибок (``self._track_error``)

Все три параметра опциональны: при отсутствии менеджера вызовы тихо
возвращают ``None`` (см. ObservableMixin._call_manager).
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ...base_manager import BaseManager, ObservableMixin
from .protocol import WorkerTaskRequest, WorkerTaskResponse


@dataclass
class PendingTask:
    """Ожидающая задача: Event для блокировки + слот для ответа."""

    event: threading.Event = field(default_factory=threading.Event)
    response: WorkerTaskResponse | None = None


class WorkerPoolDispatcher(BaseManager, ObservableMixin):
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
        logger: LoggerManager или ObservableMixin-совместимый объект.
        stats: StatsManager — приёмник метрик (опц.).
        errors: ErrorManager — приёмник трекинга исключений (опц.).
    """

    def __init__(
        self,
        send_fn: Callable,
        worker_count: int,
        timeout: float = 5.0,
        input_queue_size: int = 4,
        logger: Any = None,
        stats: Any = None,
        errors: Any = None,
    ) -> None:
        BaseManager.__init__(self, manager_name="WorkerPoolDispatcher")
        ObservableMixin.__init__(
            self,
            managers={"logger": logger, "stats": stats, "errors": errors},
        )

        self._send_fn = send_fn
        self._timeout = timeout
        self._input_queue_size = max(1, input_queue_size)

        self._worker_names: list[str] = [
            f"processor_worker_{i}" for i in range(worker_count)
        ]

        self._lock = threading.Lock()
        self._pending: dict[str, PendingTask] = {}
        self._next_worker: int = 0

        self._drops_total: int = 0
        self._dispatched_total: int = 0
        self._timeout_total: int = 0

    def initialize(self) -> bool:
        self.is_initialized = True
        return True

    def shutdown(self) -> bool:
        """Отменить все pending задачи и завершить работу."""
        with self._lock:
            for task_id, pending in list(self._pending.items()):
                pending.response = WorkerTaskResponse.error_response(
                    task_id=task_id,
                    error="dispatcher shutdown",
                )
                pending.event.set()
            self._pending.clear()
        self.is_initialized = False
        return True

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

        self._record_metric(
            "worker_pool.dispatched",
            tags={"worker": worker_name, "operation": operation_ref},
        )
        self._log_debug(
            f"Задача {request.task_id} отправлена worker={worker_name},"
            f" operation={operation_ref}"
        )

        signaled = pending.event.wait(timeout=self._timeout)

        if not signaled:
            with self._lock:
                self._pending.pop(request.task_id, None)
                self._timeout_total += 1

            self._record_metric(
                "worker_pool.timeouts",
                tags={"worker": worker_name, "operation": operation_ref},
            )
            self._log_warning(
                f"Timeout задачи {request.task_id} ({self._timeout:.1f}s),"
                f" operation={operation_ref}"
            )
            return WorkerTaskResponse.error_response(
                task_id=request.task_id,
                error="timeout",
            )

        with self._lock:
            self._pending.pop(request.task_id, None)

        if pending.response is not None:
            if pending.response.success:
                self._record_timing(
                    "worker_pool.processing_time",
                    pending.response.processing_time,
                    tags={"operation": operation_ref},
                )
            else:
                self._record_metric(
                    "worker_pool.errors",
                    tags={"operation": operation_ref},
                )
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
            self._record_metric("worker_pool.late_responses")
            self._log_warning(
                f"Late response для task_id={response.task_id}"
                f" (нет в pending), игнорируем"
            )
            return

        pending.response = response
        pending.event.set()

        self._log_debug(
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

            self._record_metric("worker_pool.drops")
            self._log_warning(
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
