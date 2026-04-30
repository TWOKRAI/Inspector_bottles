"""Worker pool — маршрутизация задач в отдельные worker-процессы (Phase 5c)."""

from services.processor.worker_pool.dispatcher import WorkerPoolDispatcher
from services.processor.worker_pool.protocol import (
    WorkerTaskRequest,
    WorkerTaskResponse,
)

__all__ = [
    "WorkerPoolDispatcher",
    "WorkerTaskRequest",
    "WorkerTaskResponse",
]
