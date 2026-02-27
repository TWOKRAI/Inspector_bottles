"""
Worker Module (Refactored) - Модуль управления потоками на основе BaseManager.

Все менеджеры воркеров наследуются от BaseManager и используют ObservableMixin.
"""

from .core.worker_manager import WorkerManager
from .core.thread_config import ThreadConfig, ThreadPriority, WorkerStatus

__all__ = [
    'WorkerManager',
    'ThreadConfig',
    'ThreadPriority',
    'WorkerStatus',
]

