"""
RingBufferFPS — скользящее окно по времени.
Плавный FPS, O(1) на кадр. При долгой паузе — O(n) очистка буфера.
"""

import time
from collections import deque
from typing import final

from ..interfaces import FPSProvider


@final
class RingBufferFPS(FPSProvider):
    """FPS по последним N кадрам в окне window_seconds."""

    __slots__ = ("_window", "_buffer", "_fps")

    def __init__(self, window_seconds: float = 1.0, max_samples: int = 120) -> None:
        if window_seconds <= 0 or max_samples < 2:
            raise ValueError("window_seconds > 0, max_samples >= 2")
        self._window = window_seconds
        self._buffer: deque[float] = deque(maxlen=max_samples)
        self._fps = 0.0

    @property
    def fps(self) -> float:
        return self._fps

    def update(self) -> float:
        now = time.perf_counter()
        self._buffer.append(now)
        cutoff = now - self._window
        while self._buffer and self._buffer[0] < cutoff:
            self._buffer.popleft()
        if len(self._buffer) >= 2:
            w = self._buffer[-1] - self._buffer[0]
            if w > 0:
                self._fps = (len(self._buffer) - 1) / w
                return self._fps
        return 0.0

    def get_fps(self) -> float:
        return self._fps

    def reset(self) -> None:
        self._buffer.clear()
        self._fps = 0.0
