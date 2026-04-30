# -*- coding: utf-8 -*-
"""
statistics_module — менеджер статистики и метрик.

Наследует ChannelRoutingManager, параметризуется через data_schema_module,
интегрируется с logger_module, command_module, router_module.
"""
from .interfaces import IStatsManager
from .configs import StatsManagerConfig
from .core import StatsManager, MetricRecord, MetricType, AggregationWindow
from .channels import LogStatsChannel, FileStatsChannel
from .adapters import StatsAdapter

__all__ = [
    "IStatsManager",
    "StatsManager",
    "StatsManagerConfig",
    "MetricRecord",
    "MetricType",
    "AggregationWindow",
    "LogStatsChannel",
    "FileStatsChannel",
    "StatsAdapter",
]
