# -*- coding: utf-8 -*-
"""
Публичный контракт statistics_module.

IStatsManager — контракт менеджера статистики и метрик.
Наследует IChannelRoutingManager, добавляет методы записи и чтения метрик.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from ..channel_routing_module.interfaces import IChannelRoutingManager


class IStatsManager(IChannelRoutingManager, ABC):
    """Контракт менеджера статистики и метрик.

    Расширяет IChannelRoutingManager методами записи метрик (counter, gauge,
    timing, histogram) и их чтения. Совместим с StatsPlugin из ObservableMixin.
    """

    @abstractmethod
    def record_metric(self, name: str, value: Any = 1, tags: Optional[Dict] = None) -> None:
        """Записать метрику (counter или произвольное значение)."""

    @abstractmethod
    def increment(self, name: str, tags: Optional[Dict] = None) -> None:
        """Увеличить счётчик на 1."""

    @abstractmethod
    def record_timing(self, name: str, duration: float, tags: Optional[Dict] = None) -> None:
        """Записать время выполнения (в секундах)."""

    @abstractmethod
    def gauge(self, name: str, value: float, tags: Optional[Dict] = None) -> None:
        """Записать текущее значение (gauge)."""

    @abstractmethod
    def histogram(self, name: str, value: float, tags: Optional[Dict] = None) -> None:
        """Записать значение в гистограмму."""

    @abstractmethod
    def get_metric(self, name: str) -> Optional[Dict[str, Any]]:
        """Получить агрегированную метрику по имени."""

    @abstractmethod
    def get_all_metrics(self) -> Dict[str, Any]:
        """Получить все метрики."""

    @abstractmethod
    def reset_metrics(self) -> None:
        """Сбросить все метрики."""

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """Получить полную диагностику (каналы, буфер, метрики)."""
