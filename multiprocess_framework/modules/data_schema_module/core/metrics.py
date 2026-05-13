"""
Метрики для модуля data_schema.

Предоставляет интерфейс для записи метрик, которые могут быть использованы StatisticsManager.
"""

from typing import Dict, Any, Optional
from functools import wraps
import time


class MetricsCollector:
    """
    Сборщик метрик для data_schema.

    Используется для записи метрик операций, которые могут быть прочитаны StatisticsManager.
    """

    def __init__(self):
        """Инициализация сборщика метрик."""
        self._metrics: Dict[str, Any] = {}
        self._counters: Dict[str, int] = {}
        self._timings: Dict[str, list] = {}

    def record_metric(
        self, metric_name: str, value: Any = 1, tags: Optional[Dict[str, str]] = None
    ):
        """
        Записать метрику.

        Args:
            metric_name: Имя метрики
            value: Значение метрики
            tags: Теги метрики
        """
        key = self._make_key(metric_name, tags)
        self._metrics[key] = {
            "name": metric_name,
            "value": value,
            "tags": tags or {},
            "timestamp": time.time(),
        }

    def increment(self, metric_name: str, tags: Optional[Dict[str, str]] = None):
        """
        Увеличить счетчик метрики.

        Args:
            metric_name: Имя метрики
            tags: Теги метрики
        """
        key = self._make_key(metric_name, tags)
        self._counters[key] = self._counters.get(key, 0) + 1

    def record_timing(
        self, metric_name: str, duration: float, tags: Optional[Dict[str, str]] = None
    ):
        """
        Записать время выполнения операции.

        Args:
            metric_name: Имя метрики
            duration: Время выполнения в секундах
            tags: Теги метрики
        """
        key = self._make_key(metric_name, tags)
        if key not in self._timings:
            self._timings[key] = []
        self._timings[key].append(
            {"duration": duration, "timestamp": time.time(), "tags": tags or {}}
        )

    def get_metrics(self) -> Dict[str, Any]:
        """
        Получить все метрики.

        Returns:
            Словарь с метриками
        """
        return {
            "metrics": self._metrics.copy(),
            "counters": self._counters.copy(),
            "timings": {
                key: {
                    "count": len(timings),
                    "total": sum(t["duration"] for t in timings),
                    "avg": sum(t["duration"] for t in timings) / len(timings)
                    if timings
                    else 0,
                    "min": min(t["duration"] for t in timings) if timings else 0,
                    "max": max(t["duration"] for t in timings) if timings else 0,
                }
                for key, timings in self._timings.items()
            },
        }

    def get_metric(
        self, metric_name: str, tags: Optional[Dict[str, str]] = None
    ) -> Optional[Any]:
        """
        Получить конкретную метрику.

        Args:
            metric_name: Имя метрики
            tags: Теги метрики

        Returns:
            Значение метрики или None
        """
        key = self._make_key(metric_name, tags)
        return self._metrics.get(key)

    def reset(self):
        """Сбросить все метрики."""
        self._metrics.clear()
        self._counters.clear()
        self._timings.clear()

    def _make_key(self, metric_name: str, tags: Optional[Dict[str, str]]) -> str:
        """Создать ключ для метрики."""
        if tags:
            tag_str = "_".join(f"{k}={v}" for k, v in sorted(tags.items()))
            return f"{metric_name}_{tag_str}"
        return metric_name


# Глобальный экземпляр сборщика метрик
_metrics_collector = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    """Получить глобальный экземпляр сборщика метрик."""
    return _metrics_collector


def record_metric(
    metric_name: str, value: Any = 1, tags: Optional[Dict[str, str]] = None
):
    """Записать метрику (удобная функция)."""
    _metrics_collector.record_metric(metric_name, value, tags)


def increment_metric(metric_name: str, tags: Optional[Dict[str, str]] = None):
    """Увеличить счетчик метрики (удобная функция)."""
    _metrics_collector.increment(metric_name, tags)


def record_timing(
    metric_name: str, duration: float, tags: Optional[Dict[str, str]] = None
):
    """Записать время выполнения (удобная функция)."""
    _metrics_collector.record_timing(metric_name, duration, tags)


def timed(metric_name: Optional[str] = None, tags: Optional[Dict[str, str]] = None):
    """
    Декоратор для автоматического измерения времени выполнения.

    Args:
        metric_name: Имя метрики (по умолчанию используется имя функции)
        tags: Теги метрики
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            name = metric_name or f"{func.__module__}.{func.__qualname__}"
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                record_timing(f"{name}.duration", duration, tags)
                increment_metric(f"{name}.success", tags)
                return result
            except Exception:
                duration = time.time() - start_time
                record_timing(f"{name}.error_duration", duration, tags)
                increment_metric(f"{name}.errors", tags)
                raise

        return wrapper

    return decorator
