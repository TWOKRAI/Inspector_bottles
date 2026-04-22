"""Handle API — единый паттерн доступа к ресурсам процесса."""

from .process_handle import ProcessHandle, QueueHandle, EventHandle
from .memory_handle import MemoryHandle

__all__ = ["ProcessHandle", "QueueHandle", "EventHandle", "MemoryHandle"]
