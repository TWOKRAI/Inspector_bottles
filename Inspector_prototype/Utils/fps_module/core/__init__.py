"""Ядро fps_module — реализации счётчиков FPS."""

from .frame_fps import FrameFPS
from .ring_buffer_fps import RingBufferFPS
from .average_fps import AverageFPS

__all__ = ("FrameFPS", "RingBufferFPS", "AverageFPS")
