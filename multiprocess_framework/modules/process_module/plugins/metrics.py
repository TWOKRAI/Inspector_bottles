"""PluginMetrics — автоматические метрики плагина.

Замеряет без кода в плагине:
- Время configure / start / shutdown (мс)
- Количество вызовов команд
- Время каждой команды (мс)
- Ошибки

Аналог: Apache NiFi processor stats.

Использование:
    metrics = PluginMetrics("color_mask")
    with metrics.measure("configure"):
        plugin.configure(ctx)

    metrics.snapshot()  # → dict для UI
"""

from __future__ import annotations

import time
from typing import Any


class PluginMetrics:
    """Автоматические метрики одного плагина."""

    def __init__(self, plugin_name: str) -> None:
        self.plugin_name = plugin_name

        # Время lifecycle-переходов (мс)
        self.configure_ms: float = 0.0
        self.start_ms: float = 0.0
        self.shutdown_ms: float = 0.0

        # Статистика команд: {command_name: {calls, total_ms, last_ms, errors}}
        self._command_stats: dict[str, dict[str, Any]] = {}

        # Общие счётчики
        self.total_errors: int = 0
        self._created_at: float = time.monotonic()

    def measure(self, phase: str) -> _MetricsTimer:
        """Context manager для замера времени фазы.

        Использование:
            with metrics.measure("configure"):
                plugin.configure(ctx)
        """
        return _MetricsTimer(self, phase)

    def record_command(self, command_name: str, duration_ms: float, error: bool = False) -> None:
        """Записать метрику вызова команды."""
        if command_name not in self._command_stats:
            self._command_stats[command_name] = {
                "calls": 0,
                "total_ms": 0.0,
                "last_ms": 0.0,
                "errors": 0,
            }

        stats = self._command_stats[command_name]
        stats["calls"] += 1
        stats["total_ms"] += duration_ms
        stats["last_ms"] = duration_ms

        if error:
            stats["errors"] += 1
            self.total_errors += 1

    def snapshot(self) -> dict[str, Any]:
        """Снимок метрик для UI / мониторинга.

        Returns:
            dict с lifecycle timings, command stats, uptime.
        """
        uptime = time.monotonic() - self._created_at

        return {
            "plugin_name": self.plugin_name,
            "uptime_s": round(uptime, 1),
            "lifecycle": {
                "configure_ms": round(self.configure_ms, 2),
                "start_ms": round(self.start_ms, 2),
                "shutdown_ms": round(self.shutdown_ms, 2),
            },
            "commands": {
                name: {
                    "calls": s["calls"],
                    "avg_ms": round(s["total_ms"] / max(s["calls"], 1), 2),
                    "last_ms": round(s["last_ms"], 2),
                    "errors": s["errors"],
                }
                for name, s in self._command_stats.items()
            },
            "total_errors": self.total_errors,
        }


class _MetricsTimer:
    """Context manager для замера времени."""

    def __init__(self, metrics: PluginMetrics, phase: str) -> None:
        self._metrics = metrics
        self._phase = phase
        self._start: float = 0.0

    def __enter__(self) -> _MetricsTimer:
        self._start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        elapsed_ms = (time.monotonic() - self._start) * 1000

        if self._phase == "configure":
            self._metrics.configure_ms = elapsed_ms
        elif self._phase == "start":
            self._metrics.start_ms = elapsed_ms
        elif self._phase == "shutdown":
            self._metrics.shutdown_ms = elapsed_ms
        else:
            # Произвольная фаза — записываем как команду
            self._metrics.record_command(
                self._phase, elapsed_ms, error=exc_type is not None
            )

        if exc_type is not None:
            self._metrics.total_errors += 1
