# -*- coding: utf-8 -*-
"""
SQLMetricsCollector — реализация IMetricsCollector.

Интеграция с ObservableMixin (_record_timing, _record_metric).
"""
from __future__ import annotations

from typing import Optional


class SQLMetricsCollector:
    """Сборщик метрик для SQL-операций.

    Делегирует в ObservableMixin менеджера если передан.
    """

    def __init__(self, manager: Optional[Any] = None):
        self._manager = manager

    def record_query_time(self, sql: str, duration_ms: float) -> None:
        """Записать время выполнения запроса."""
        if self._manager and hasattr(self._manager, "_record_timing"):
            self._manager._record_timing("db.query", duration_ms / 1000.0)

    def record_pool_stats(
        self, checkedin: int, checkedout: int, overflow: int = 0
    ) -> None:
        """Записать статистику пула соединений."""
        if self._manager and hasattr(self._manager, "emit_event"):
            self._manager.emit_event(
                "db.pool.stats",
                {"checkedin": checkedin, "checkedout": checkedout, "overflow": overflow},
            )
