"""LatencyTracker — измерение сквозной задержки обработки.

Без numpy: расчёт percentiles вручную через sorted().
"""
from __future__ import annotations

import collections
import time
from typing import Any


class LatencyTracker:
    """Трекер сквозной latency (end-to-end).

    Буфер хранит последние buffer_size измерений в миллисекундах.
    Каждые log_interval_sec секунд выводит p50/p95/p99 в лог.
    """

    def __init__(
        self,
        log_interval_sec: float = 10.0,
        buffer_size: int = 1000,
        logger: Any = None,
    ) -> None:
        self._buffer: collections.deque[float] = collections.deque(maxlen=buffer_size)
        self._log_interval = log_interval_sec
        self._last_log_time = time.time()
        self._log = logger

    def record(self, e2e_ms: float) -> None:
        """Записать новое измерение latency в буфер."""
        self._buffer.append(e2e_ms)

    def percentiles(self) -> dict[str, float]:
        """Вычислить p50, p95, p99 из накопленного буфера."""
        if not self._buffer:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
        sorted_vals = sorted(self._buffer)
        n = len(sorted_vals)
        return {
            "p50": sorted_vals[int(n * 0.50)],
            "p95": sorted_vals[int(n * 0.95)] if n > 1 else sorted_vals[0],
            "p99": sorted_vals[int(n * 0.99)] if n > 1 else sorted_vals[0],
        }

    def maybe_log(self) -> None:
        """Залогировать percentiles если прошёл log_interval_sec с последнего лога."""
        now = time.time()
        if now - self._last_log_time >= self._log_interval:
            p = self.percentiles()
            if self._log is not None:
                self._log._log_info(
                    f"Latency p50={p['p50']:.1f}ms p95={p['p95']:.1f}ms p99={p['p99']:.1f}ms"
                )
            self._last_log_time = now


__all__ = ["LatencyTracker"]
