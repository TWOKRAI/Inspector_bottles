# -*- coding: utf-8 -*-
"""
LogStatsChannel — канал вывода метрик в LoggerManager.

При write(data) вызывает logger_manager.performance() с агрегированным снапшотом.
"""
from typing import Any, Dict, Optional

from ...channel_routing_module.interfaces import IChannel


class LogStatsChannel(IChannel):
    """Канал записи метрик в лог через LoggerManager."""

    def __init__(
        self,
        logger_manager: Any,
        level: str = "INFO",
        name: str = "log_stats",
    ) -> None:
        """
        Args:
            logger_manager: LoggerManager для записи
            level: Уровень логирования (INFO, DEBUG, ...)
            name: Имя канала
        """
        self._logger = logger_manager
        self._level_str = level.upper()
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def channel_type(self) -> str:
        return "log"

    def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Записать снапшот метрик в лог."""
        try:
            if not self._logger:
                return {"status": "error", "error": "LoggerManager not set", "channel": self.name}

            metrics = data.get("metrics", [])
            total = data.get("total_count", 0)
            ts = data.get("timestamp", 0)

            msg = f"metrics snapshot (ts={ts:.0f}, count={total}): {metrics}"

            # LoggerManager.performance(level, message, module, **extra)
            from ...logger_module.core.log_config import LogLevel

            log_level = getattr(LogLevel, self._level_str, LogLevel.INFO)
            self._logger.performance(log_level, msg, module="stats")

            return {"status": "success", "channel": self.name}
        except Exception as e:
            return {"status": "error", "error": str(e), "channel": self.name}

    def close(self) -> None:
        """Закрыть канал (no-op для лога)."""
        pass

    def get_info(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.channel_type,
            "level": self._level_str,
            "active": True,
        }
