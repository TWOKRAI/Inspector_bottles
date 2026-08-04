# -*- coding: utf-8 -*-
"""
Публичный контракт statistics_module.

IStatsManager — контракт менеджера статистики и метрик.
Наследует IChannelRoutingManager, добавляет методы записи и чтения метрик.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from ..channel_routing_module.interfaces import IChannelRoutingManager

#: Имя источника, которым модуль штампует свои записи (Ф2.6, решение Р-2.6-В).
#:
#: Точка штампа ровно одна (``channels/log_stats_channel.py``), но именно она даёт
#: **самый тяжёлый поток логов в системе**: на прогоне 2026-08-03 записи под этим
#: именем занимали 54.9% веса ``system.log`` у ProcessManager и 23–26% у остальных
#: процессов. Правило маршрутизации для неё — первое, ради чего заводился механизм
#: Ф2.2, поэтому имя обязано быть ссылкой, а не второй копией строки.
#:
#: **Значение — точечное имя пакета, а не короткий ярлык** (Р-2.6-Д, правка после
#: ревью решений). Плоское имя — лист без поддерева: правило по префиксу на нём не
#: работает, и каждый новый файл модуля пришлось бы заводить в конфиге руками.
#: Точечное имя даёт обратное — правило ``multiprocess_framework.modules`` действует
#: на всё поддерево, а новый файл наследует его без единой правки. Так же выводят имя
#: логгера stdlib (``getLogger(__name__)``), logback (FQCN), .NET (``ILogger<T>``) и
#: OTel (``InstrumentationScope.name``); короткие ручки в индустрии существуют, но как
#: алиас КОНФИГА (Spring ``logging.group``) — у нас это задача 2.5, а не личность записи.
#:
#: В файл имя пишется сокращённым (``LoggerChannelSchema.name_max_len``): без этого
#: переход дал бы +4.7…16.4% к весу логов — замер там же.
LOG_SOURCE = "multiprocess_framework.modules.statistics_module"


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


# Публичный контракт модуля (Ф8 H.1 / NEW-10): перечислен явно, чтобы
# случайный top-level импорт не становился частью API.
__all__ = [
    "IStatsManager",
]
