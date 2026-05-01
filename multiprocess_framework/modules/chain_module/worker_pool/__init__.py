"""worker_pool — протокол IPC и диспетчер задач для worker-процессов."""

from .protocol import WorkerTaskRequest, WorkerTaskResponse
from .dispatcher import WorkerPoolDispatcher

__all__ = [
    "WorkerTaskRequest",
    "WorkerTaskResponse",
    "WorkerPoolDispatcher",
]
