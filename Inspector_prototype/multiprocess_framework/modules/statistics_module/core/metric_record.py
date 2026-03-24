# -*- coding: utf-8 -*-
"""
MetricRecord — dataclass для хранения и агрегации метрик.

Типы: counter, gauge, timing, histogram.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class MetricType(str, Enum):
    """Тип метрики."""

    COUNTER = "counter"
    GAUGE = "gauge"
    TIMING = "timing"
    HISTOGRAM = "histogram"


@dataclass
class MetricRecord:
    """Запись метрики с поддержкой агрегации.

    counter   — суммирует значения
    gauge     — хранит последнее значение
    timing    — хранит min/max/avg/p95/count
    histogram — хранит распределение (список значений для перцентилей)
    """

    name: str
    metric_type: MetricType
    tags: Dict[str, str] = field(default_factory=dict)

    # counter
    count: float = 0.0

    # gauge
    value: Optional[float] = None

    # timing
    timing_values: List[float] = field(default_factory=list)
    timing_min: Optional[float] = None
    timing_max: Optional[float] = None
    timing_avg: Optional[float] = None
    timing_p95: Optional[float] = None

    # histogram
    histogram_values: List[float] = field(default_factory=list)

    def add_counter(self, value: float = 1.0) -> None:
        """Добавить к счётчику."""
        self.count += value

    def set_gauge(self, value: float) -> None:
        """Установить gauge."""
        self.value = value

    def add_timing(self, duration: float) -> None:
        """Добавить значение timing."""
        self.timing_values.append(duration)

    def add_histogram(self, value: float) -> None:
        """Добавить значение в гистограмму."""
        self.histogram_values.append(value)

    def aggregate(self) -> Dict[str, Any]:
        """Вычислить агрегированный снапшот для flush."""
        result: Dict[str, Any] = {
            "name": self.name,
            "type": self.metric_type.value,
            "tags": dict(self.tags),
        }

        if self.metric_type == MetricType.COUNTER:
            result["count"] = self.count

        elif self.metric_type == MetricType.GAUGE:
            result["value"] = self.value

        elif self.metric_type == MetricType.TIMING:
            if self.timing_values:
                sorted_vals = sorted(self.timing_values)
                n = len(sorted_vals)
                result["count"] = n
                result["min"] = sorted_vals[0]
                result["max"] = sorted_vals[-1]
                result["avg"] = sum(sorted_vals) / n
                p95_idx = int(n * 0.95) - 1
                result["p95"] = sorted_vals[max(0, p95_idx)]
            else:
                result["count"] = 0
                result["min"] = result["max"] = result["avg"] = result["p95"] = None

        elif self.metric_type == MetricType.HISTOGRAM:
            if self.histogram_values:
                sorted_vals = sorted(self.histogram_values)
                n = len(sorted_vals)
                result["count"] = n
                result["min"] = sorted_vals[0]
                result["max"] = sorted_vals[-1]
                result["avg"] = sum(sorted_vals) / n
                p95_idx = int(n * 0.95) - 1
                result["p95"] = sorted_vals[max(0, p95_idx)]
            else:
                result["count"] = 0
                result["min"] = result["max"] = result["avg"] = result["p95"] = None

        return result

    def to_dict(self) -> Dict[str, Any]:
        """Сериализация для get_metric / get_all_metrics."""
        return self.aggregate()
