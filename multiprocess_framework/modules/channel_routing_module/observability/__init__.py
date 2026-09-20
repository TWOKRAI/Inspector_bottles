# -*- coding: utf-8 -*-
"""
observability — фасад наблюдаемости модуля (ObservabilityHub) поверх channel_routing.

Слой уровня 0 конструктора: сводит все ошибки/логи/статистику подмодулей и
классов к трём bounded-каналам на фасаде модуля. Владелец дренирует их по
heartbeat в LoggerManager / ErrorManager / StatsManager.

Публичный API:
    ObservabilityHub  — перехватчик наблюдаемости одного модуля (3 канала)
    BoundedChannel    — потокобезопасный bounded-канал с drop-политикой
    BatchDrainWorker  — дренаж пачкой из фонового потока поверх канала
                        (Task 3.3): цена эмитента — только постановка,
                        имя счётчика потерь — параметр плоскости
    NumberRecord      — ОДНА форма числа плоскости (Task 3.1, К3): три диалекта
                        сходятся в ней, а не в ветках каждого читателя
    LoggerLike / StatsLike / ErrorLike — duck-type контракты слотов ObservableMixin

См. README.md и DECISIONS.md (ADR ObservabilityHub).
"""

from .batch_drain import BatchDrainWorker
from .bounded_channel import DROP_NEWEST, DROP_OLDEST, BoundedChannel
from .observability_hub import (
    KIND_ERROR,
    KIND_LOG,
    KIND_OBSERVATION,
    KIND_STATS,
    METRIC_COUNTER,
    METRIC_GAUGE,
    METRIC_TIMING,
    STATS_AGGREGATE_KEY,
    ObservabilityHub,
)
from .drain_adapter import ObservabilityDrainAdapter
from .observability_store import ObservabilityStore, resolve_default_db_path
from .store_tap import (
    ORIGIN_ERROR_MANAGER,
    ORIGIN_FIELD,
    ORIGIN_STATS_SNAPSHOT,
    STORE_EVICTED_COUNTER,
    StoreTapChannel,
)
from .number_record import NumberKind, NumberRecord, number_metric_identity
from .record_display import NUMBER_SEVERITY, hub_record_to_display, log_record_to_display
from .record_forward_channel import FORWARD_COMMAND, RecordForwardChannel
from .protocols import ErrorLike, LoggerLike, StatsLike

__all__ = [
    "ObservabilityHub",
    "ObservabilityDrainAdapter",
    "ObservabilityStore",
    "StoreTapChannel",
    "ORIGIN_FIELD",
    "ORIGIN_ERROR_MANAGER",
    "ORIGIN_STATS_SNAPSHOT",
    "NUMBER_SEVERITY",
    "NumberRecord",
    "NumberKind",
    "number_metric_identity",
    "RecordForwardChannel",
    "FORWARD_COMMAND",
    "hub_record_to_display",
    "log_record_to_display",
    "resolve_default_db_path",
    "BoundedChannel",
    "BatchDrainWorker",
    "STORE_EVICTED_COUNTER",
    "DROP_OLDEST",
    "DROP_NEWEST",
    "LoggerLike",
    "StatsLike",
    "ErrorLike",
    "KIND_LOG",
    "KIND_ERROR",
    "KIND_STATS",
    "KIND_OBSERVATION",
    "METRIC_GAUGE",
    "METRIC_COUNTER",
    "METRIC_TIMING",
    "STATS_AGGREGATE_KEY",
]
