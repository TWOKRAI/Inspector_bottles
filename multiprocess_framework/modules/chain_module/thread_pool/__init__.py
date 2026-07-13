"""thread_pool — пул параллельного исполнения шагов поверх worker_module."""

from .pool import ChainThreadPool
from .worker_pool_executor import WorkerPoolExecutor

__all__ = ["ChainThreadPool", "WorkerPoolExecutor"]
