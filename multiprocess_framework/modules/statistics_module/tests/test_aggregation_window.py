# -*- coding: utf-8 -*-
"""
Тесты для AggregationWindow.
"""

from ..core.aggregation_window import AggregationWindow
from ...channel_routing_module.interfaces import IBufferStrategy


class TestAggregationWindow:
    """Тесты AggregationWindow."""

    def test_implements_interface(self):
        """Проверка реализации IBufferStrategy."""
        flushed = []

        def flush_fn(channel: str, batch: list):
            flushed.append((channel, batch))

        buf = AggregationWindow(flush_fn=flush_fn, flush_interval=60.0)
        assert isinstance(buf, IBufferStrategy)

    def test_enqueue_and_flush(self):
        """Накопление и flush."""
        flushed = []

        def flush_fn(channel: str, batch: list):
            flushed.append((channel, batch))

        buf = AggregationWindow(flush_fn=flush_fn, flush_interval=60.0)
        buf.enqueue("log", {"type": "counter", "name": "x", "value": 1, "tags": {}})
        buf.enqueue("log", {"type": "counter", "name": "x", "value": 2, "tags": {}})

        buf.flush_all()

        assert len(flushed) >= 1
        ch, batch = flushed[0]
        assert ch == "log"
        assert len(batch) == 1
        snapshot = batch[0]
        assert "metrics" in snapshot
        assert "timestamp" in snapshot
        metrics = snapshot["metrics"]
        assert len(metrics) >= 1
        m = metrics[0]
        assert m["name"] == "x"
        assert m["type"] == "counter"
        assert m.get("count", 0) >= 3

    def test_stats(self):
        """Статистика буфера."""
        buf = AggregationWindow(flush_fn=lambda c, b: None, flush_interval=60.0)
        buf.enqueue("ch", {"type": "counter", "name": "a", "value": 1})

        s = buf.stats
        assert s["type"] == "aggregation"
        assert s["total_enqueued"] >= 1
