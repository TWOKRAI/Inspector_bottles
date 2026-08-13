# -*- coding: utf-8 -*-
"""
statistics_module — менеджер статистики и метрик.

Наследует ChannelRoutingManager, параметризуется через data_schema_module,
интегрируется с logger_module, command_module, router_module.
"""

from .interfaces import IStatsManager
from .configs import StatsManagerConfig
from .configs.stats_config import DEFAULT_MAX_SERIES
from .core import StatsManager, MetricRecord, MetricType, AggregationWindow
from .core.cardinality_guard import CardinalityGuard
from .core.metric_record import DEFAULT_DURATION_BUCKETS_SEC
from .channels import LogStatsChannel, FileStatsChannel
from .channels.log_stats_channel import DEFAULT_LOG_LINE_MAX_BYTES
from .adapters import StatsAdapter

__all__ = [
    "IStatsManager",
    "StatsManager",
    "StatsManagerConfig",
    "MetricRecord",
    "MetricType",
    "AggregationWindow",
    "CardinalityGuard",
    "DEFAULT_DURATION_BUCKETS_SEC",
    "DEFAULT_MAX_SERIES",
    "LogStatsChannel",
    "FileStatsChannel",
    "DEFAULT_LOG_LINE_MAX_BYTES",
    "StatsAdapter",
]
