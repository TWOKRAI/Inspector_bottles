# -*- coding: utf-8 -*-
"""
MetricsCollector — сборщик метрик для data_schema_module.

Перемещён в extensions/ так как является опциональным компонентом.
Не импортируется автоматически в основном __init__.py.

Использование:
    from multiprocess_framework.modules.data_schema_module.extensions.metrics import MetricsCollector, get_metrics_collector
"""
from ..core.metrics import (
    MetricsCollector,
    get_metrics_collector,
    record_metric,
    increment_metric,
    record_timing,
    timed,
)

__all__ = [
    "MetricsCollector",
    "get_metrics_collector",
    "record_metric",
    "increment_metric",
    "record_timing",
    "timed",
]
