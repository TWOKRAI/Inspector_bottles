"""SHM utilities: ring-buffer для безопасного fan-out кадров (AD-6), cleanup осиротевших сегментов."""

from .cleanup import cleanup_stale_shm
from .registry import ShmRegistry
from .ring_buffer import RingBufferReader, RingBufferWriter

__all__ = ["RingBufferWriter", "RingBufferReader", "cleanup_stale_shm", "ShmRegistry"]
