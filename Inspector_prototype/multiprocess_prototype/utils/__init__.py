"""
Утилиты Inspector Prototype.

- frame_generator: имитация камеры (тестовые кадры)
- webcam_capture: захват с веб-камеры (cv2.VideoCapture)
- shm_utils: чтение кадров из SharedMemory
"""

from .frame_generator import FrameGenerator
from .webcam_capture import WebcamCapture
from .shm_utils import read_frame_from_shm

__all__ = ["FrameGenerator", "WebcamCapture", "read_frame_from_shm"]
