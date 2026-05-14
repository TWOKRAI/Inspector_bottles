# -*- coding: utf-8 -*-
"""
AggregationWindow — буферная стратегия с агрегацией метрик.

Реализует IBufferStrategy. Вместо простого батчинга агрегирует метрики
за окно: counter — сумма, gauge — последнее, timing — min/max/avg/p95,
histogram — распределение. При flush() отправляет агрегированный снапшот.
"""

import time
import threading
from typing import Any, Callable, Dict, List, Optional

from ...channel_routing_module.interfaces import IBufferStrategy
from .metric_record import MetricRecord, MetricType


def _metric_key(name: str, tags: Optional[Dict] = None) -> str:
    """Ключ для группировки метрик (name + sorted tags)."""
    if not tags:
        return name
    parts = [name] + [f"{k}:{v}" for k, v in sorted(tags.items())]
    return "|".join(parts)


class AggregationWindow(IBufferStrategy):
    """Буфер с агрегацией метрик перед flush.

    enqueue(channel, data): data должен содержать type, name, value/tags.
    flush: агрегирует все метрики, вызывает flush_fn(channel, [snapshot])
    для каждого канала.
    """

    def __init__(
        self,
        flush_fn: Callable[[str, List[Dict[str, Any]]], Any],
        flush_interval: float = 10.0,
    ) -> None:
        """
        Args:
            flush_fn: fn(channel_name: str, batch: List[dict]) — вызывается при flush.
                      batch содержит один элемент — агрегированный снапшот.
            flush_interval: Интервал периодического flush, сек.
        """
        self._flush_fn = flush_fn
        self._flush_interval = flush_interval

        self._lock = threading.Lock()
        self._metrics: Dict[str, MetricRecord] = {}
        self._channels_seen: set = set()

        self._total_enqueued: int = 0
        self._total_flushes: int = 0
        self._errors: int = 0

        self._timer_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def _ensure_record(
        self,
        name: str,
        metric_type: MetricType,
        tags: Optional[Dict] = None,
    ) -> MetricRecord:
        """Получить или создать MetricRecord."""
        key = _metric_key(name, tags or {})
        if key not in self._metrics:
            self._metrics[key] = MetricRecord(
                name=name,
                metric_type=metric_type,
                tags=dict(tags or {}),
            )
        return self._metrics[key]

    def _merge_data(self, data: Dict[str, Any]) -> None:
        """Добавить данные в агрегацию."""
        mtype = data.get("type", "counter")
        name = data.get("name", "unknown")
        tags = data.get("tags") or {}
        value = data.get("value", 1.0)

        try:
            mt = MetricType(mtype) if isinstance(mtype, str) else mtype
        except (ValueError, TypeError):
            mt = MetricType.COUNTER

        rec = self._ensure_record(name, mt, tags)

        if mt == MetricType.COUNTER:
            rec.add_counter(float(value))
        elif mt == MetricType.GAUGE:
            rec.set_gauge(float(value))
        elif mt == MetricType.TIMING:
            rec.add_timing(float(value))
        elif mt == MetricType.HISTOGRAM:
            rec.add_histogram(float(value))

    def enqueue(
        self,
        channel: str,
        data: Dict[str, Any],
        priority: str = "normal",
    ) -> None:
        """Добавить метрику в агрегацию."""
        with self._lock:
            self._channels_seen.add(channel)
            self._merge_data(data)
            self._total_enqueued += 1

    def flush(self, channel: Optional[str] = None) -> None:
        """Принудительно сбросить буфер."""
        if channel is not None:
            self._flush_channel(channel)
        else:
            self.flush_all()

    def flush_all(self) -> None:
        """Сбросить все каналы — отправить агрегированный снапшот."""
        with self._lock:
            channels = list(self._channels_seen)
            snapshot = self._build_snapshot()
            self._metrics.clear()
            self._total_flushes += 1

        for ch in channels:
            try:
                self._flush_fn(ch, [snapshot])
            except Exception:
                self._errors += 1

    def _build_snapshot(self) -> Dict[str, Any]:
        """Построить агрегированный снапшот."""
        metrics_list = [rec.aggregate() for rec in self._metrics.values()]
        return {
            "timestamp": time.time(),
            "metrics": metrics_list,
            "total_count": len(metrics_list),
        }

    def _flush_channel(self, channel: str) -> None:
        """Сбросить один канал (отправляет полный снапшот)."""
        with self._lock:
            snapshot = self._build_snapshot()
            self._metrics.clear()
            self._total_flushes += 1

        try:
            self._flush_fn(channel, [snapshot])
        except Exception:
            self._errors += 1

    def start(self) -> None:
        """Запустить фоновый поток периодического flush."""
        if self._timer_thread and self._timer_thread.is_alive():
            return
        self._stop_event.clear()
        self._timer_thread = threading.Thread(
            target=self._timer_worker,
            name="aggregation-window-timer",
            daemon=True,
        )
        self._timer_thread.start()

    def stop(self) -> None:
        """Остановить таймер и выполнить финальный flush."""
        self._stop_event.set()
        if self._timer_thread and self._timer_thread.is_alive():
            self._timer_thread.join(timeout=5.0)
        self._timer_thread = None
        self.flush_all()

    def _timer_worker(self) -> None:
        """Периодический flush."""
        while not self._stop_event.is_set():
            self._stop_event.wait(self._flush_interval)
            if not self._stop_event.is_set():
                try:
                    self.flush_all()
                except Exception:
                    pass

    @property
    def stats(self) -> Dict[str, Any]:
        """Статистика буфера."""
        with self._lock:
            pending = len(self._metrics)
        return {
            "type": "aggregation",
            "total_enqueued": self._total_enqueued,
            "total_flushes": self._total_flushes,
            "errors": self._errors,
            "pending_metrics": pending,
            "channels": list(self._channels_seen),
            "running": bool(self._timer_thread and self._timer_thread.is_alive()),
        }
