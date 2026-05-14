# -*- coding: utf-8 -*-
"""
StatsAdapter — связывает StatsManager с CommandManager.

Регистрирует команды get_metrics, get_metric, reset_metrics, stats_snapshot,
flush_stats для доступа к метрикам через CommandManager.
"""

from typing import Any, Optional

from ...base_manager.adapters.base_adapter import BaseAdapter
from ..interfaces import IStatsManager


class StatsAdapter(BaseAdapter):
    """Адаптер интеграции StatsManager с CommandManager."""

    def __init__(
        self,
        stats_manager: IStatsManager,
        process: Optional[Any] = None,
        adapter_name: str = "StatsAdapter",
    ) -> None:
        super().__init__(
            manager=stats_manager,
            process=process,
            adapter_name=adapter_name,
        )
        self._stats = stats_manager

    def setup(self) -> bool:
        """Зарегистрировать команды статистики в CommandManager."""
        try:
            if not self.process or not hasattr(self.process, "command_manager"):
                self._log("error", "Process or CommandManager not available")
                return False

            cmd_mgr = self.process.command_manager
            stats = self._stats

            cmd_mgr.register_command(
                "get_metrics",
                lambda data=None: stats.get_all_metrics(),
                tags=["stats"],
            )
            cmd_mgr.register_command(
                "get_metric",
                lambda data: stats.get_metric(data.get("name")) if isinstance(data, dict) else None,
                tags=["stats"],
            )
            cmd_mgr.register_command(
                "reset_metrics",
                lambda data=None: stats.reset_metrics() or None,
                tags=["stats"],
            )
            cmd_mgr.register_command(
                "stats_snapshot",
                lambda data=None: stats.get_stats(),
                tags=["stats", "diagnostics"],
            )
            cmd_mgr.register_command(
                "flush_stats",
                lambda data=None: stats.flush() or None,
                tags=["stats"],
            )

            self._initialized = True
            self._log(
                "info",
                "StatsAdapter: commands get_metrics, get_metric, reset_metrics, stats_snapshot, flush_stats registered",
            )
            return True

        except Exception as exc:
            self._log("error", f"StatsAdapter setup failed: {exc}")
            return False

    def is_initialized(self) -> bool:
        return self._initialized
