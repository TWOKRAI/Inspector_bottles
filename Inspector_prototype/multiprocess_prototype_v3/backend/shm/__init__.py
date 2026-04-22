"""SHM utilities: ring-buffer для безопасного fan-out кадров (AD-6)."""

from .ring_buffer import RingBufferReader, RingBufferWriter

__all__ = ["RingBufferWriter", "RingBufferReader"]
