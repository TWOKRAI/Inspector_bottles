"""
Утилиты Inspector Prototype.

- frame_generator: имитация камеры (тестовые кадры)
- shm_utils: чтение кадров из SharedMemory
"""

from .frame_generator import FrameGenerator
from .shm_utils import read_frame_from_shm

__all__ = ["FrameGenerator", "read_frame_from_shm"]
