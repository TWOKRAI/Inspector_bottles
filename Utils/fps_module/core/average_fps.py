"""
AverageFPS — скользящее среднее FPS за последние N измерений.
Каждое измерение — FPS за interval секунд.
"""

from collections import deque
from typing import Optional, final

from ..interfaces import FPSProvider
from .frame_fps import FrameFPS


@final
class AverageFPS(FPSProvider):
    """
    FPS + среднее за последние average_samples измерений.
    average_samples=None — только текущий FPS.
    """

    __slots__ = ("_base", "_history", "_window", "_last", "_sum")

    def __init__(
        self,
        interval: float = 1.0,
        average_samples: Optional[int] = None,
    ) -> None:
        if interval <= 0:
            raise ValueError("interval must be positive")
        self._base = FrameFPS(interval=interval)
        self._window = average_samples
        self._last = 0.0
        self._history = deque(maxlen=average_samples if average_samples else 1)
        self._sum = 0.0

    @property
    def fps(self) -> float:
        return self._last

    @property
    def average_fps(self) -> float:
        """Среднее за последние average_samples измерений."""
        if self._window is None or len(self._history) == 0:
            return self._last
        return self._sum / len(self._history)

    def update(self) -> float:
        result = self._base.update()
        if result > 0:
            self._last = result
            if self._window is not None and self._history.maxlen:
                if len(self._history) == self._history.maxlen:
                    self._sum -= self._history[0]
                self._history.append(result)
                self._sum += result
        return result

    def get_fps(self) -> float:
        return self._last

    def reset(self) -> None:
        self._base.reset()
        self._history.clear()
        self._last = 0.0
        self._sum = 0.0
