"""
fps_module — счётчик кадров. FrameFPS, RingBufferFPS, AverageFPS.
Не thread-safe.
"""

from .interfaces import FPSProvider
from .core import FrameFPS, RingBufferFPS, AverageFPS

__all__ = ("FPSProvider", "FrameFPS", "RingBufferFPS", "AverageFPS")
