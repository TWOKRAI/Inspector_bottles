"""
FrameFPS — минимальные накладные расходы.
Один вызов time.perf_counter() на update(), без аллокаций в горячем пути.
"""

import time
from typing import final

from ..interfaces import FPSProvider


@final
class FrameFPS(FPSProvider):
    """Быстрый счётчик. Обновляет FPS каждые interval секунд."""

    __slots__ = ("_interval", "_frames", "_start", "_fps", "_last_update")

    def __init__(self, interval: float = 1.0) -> None:
        if interval <= 0:
            raise ValueError("interval must be positive")
        self._interval = interval
        self._frames = 0
        self._start = time.perf_counter()
        self._fps = 0.0
        self._last_update = self._start

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def instantaneous_fps(self) -> float:
        """Мгновенный FPS (кадры / время с последнего обновления). Для плавного UI."""
        elapsed = time.perf_counter() - self._last_update
        if elapsed > 0 and self._frames > 0:
            return self._frames / elapsed
        return self._fps

    def update(self) -> float:
        self._frames += 1
        now = time.perf_counter()
        elapsed = now - self._start
        if elapsed >= self._interval:
            self._fps = self._frames / elapsed
            self._frames = 0
            self._start = now
            self._last_update = now
            return self._fps
        return 0.0

    def get_fps(self) -> float:
        return self._fps

    def reset(self) -> None:
        self._frames = 0
        self._start = time.perf_counter()
        self._fps = 0.0
        self._last_update = self._start
