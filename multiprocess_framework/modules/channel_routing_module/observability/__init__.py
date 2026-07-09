# -*- coding: utf-8 -*-
"""
observability — фасад наблюдаемости модуля (ObservabilityHub) поверх channel_routing.

Слой уровня 0 конструктора: сводит все ошибки/логи/статистику подмодулей и
классов к трём bounded-каналам на фасаде модуля. Владелец дренирует их по
heartbeat в LoggerManager / ErrorManager / StatsManager.

Публичный API:
    ObservabilityHub  — перехватчик наблюдаемости одного модуля (3 канала)
    BoundedChannel    — потокобезопасный bounded-канал с drop-политикой
    LoggerLike / StatsLike / ErrorLike — duck-type контракты слотов ObservableMixin

См. README.md и DECISIONS.md (ADR ObservabilityHub).
"""

from .bounded_channel import DROP_NEWEST, DROP_OLDEST, BoundedChannel
from .observability_hub import (
    KIND_ERROR,
    KIND_LOG,
    KIND_STATS,
    METRIC_COUNTER,
    METRIC_GAUGE,
    METRIC_TIMING,
    ObservabilityHub,
)
from .drain_adapter import ObservabilityDrainAdapter
from .observability_store import ObservabilityStore, resolve_default_db_path
from .store_tap import StoreTapChannel
from .record_display import hub_record_to_display, log_record_to_display
from .record_forward_channel import FORWARD_COMMAND, RecordForwardChannel
from .protocols import ErrorLike, LoggerLike, StatsLike

__all__ = [
    "ObservabilityHub",
    "ObservabilityDrainAdapter",
    "ObservabilityStore",
    "StoreTapChannel",
    "RecordForwardChannel",
    "FORWARD_COMMAND",
    "hub_record_to_display",
    "log_record_to_display",
    "resolve_default_db_path",
    "BoundedChannel",
    "DROP_OLDEST",
    "DROP_NEWEST",
    "LoggerLike",
    "StatsLike",
    "ErrorLike",
    "KIND_LOG",
    "KIND_ERROR",
    "KIND_STATS",
    "METRIC_GAUGE",
    "METRIC_COUNTER",
    "METRIC_TIMING",
]
