"""SHM Ring Buffer и утилиты — generic реализации для fan-out кадров между процессами."""

from .cleanup import cleanup_orphaned_by_prefix, cleanup_stale_shm
from .registry import ShmRegistry
from .ring_buffer import RingBufferReader, RingBufferWriter

__all__ = [
    "RingBufferWriter",
    "RingBufferReader",
    "ShmRegistry",
    "cleanup_stale_shm",
    "cleanup_orphaned_by_prefix",
]
