"""Тесты LatencyTracker."""
from __future__ import annotations

import time

import pytest

from multiprocess_framework.modules.chain_module.metrics.latency import LatencyTracker


class TestLatencyTrackerPercentiles:
    def test_empty_returns_zeros(self):
        tracker = LatencyTracker()
        p = tracker.percentiles()
        assert p == {"p50": 0.0, "p95": 0.0, "p99": 0.0}

    def test_single_value(self):
        tracker = LatencyTracker()
        tracker.record(50.0)
        p = tracker.percentiles()
        assert p["p50"] == 50.0
        assert p["p95"] == 50.0
        assert p["p99"] == 50.0

    def test_monotonic_sequence(self):
        tracker = LatencyTracker()
        for ms in range(1, 101):  # 1..100
            tracker.record(float(ms))
        p = tracker.percentiles()
        # p50 должен быть около 50
        assert 45 <= p["p50"] <= 55
        assert p["p95"] >= p["p50"]
        assert p["p99"] >= p["p95"]

    def test_two_values(self):
        tracker = LatencyTracker()
        tracker.record(10.0)
        tracker.record(20.0)
        p = tracker.percentiles()
        # int(2 * 0.50) = 1 → sorted[1] = 20.0
        assert p["p50"] == 20.0
        assert p["p95"] == 20.0
        assert p["p99"] == 20.0

    def test_buffer_size_limit(self):
        tracker = LatencyTracker(buffer_size=5)
        for i in range(10):
            tracker.record(float(i))
        # Только последние 5 значений: 5..9
        p = tracker.percentiles()
        assert p["p50"] >= 5.0

    def test_all_same_values(self):
        tracker = LatencyTracker()
        for _ in range(10):
            tracker.record(42.0)
        p = tracker.percentiles()
        assert p["p50"] == 42.0
        assert p["p95"] == 42.0
        assert p["p99"] == 42.0


class TestLatencyTrackerRecord:
    def test_record_accumulates(self):
        tracker = LatencyTracker(buffer_size=100)
        for i in range(50):
            tracker.record(float(i))
        p = tracker.percentiles()
        # Есть данные, не нули
        assert p["p50"] > 0

    def test_record_accepts_float(self):
        tracker = LatencyTracker()
        tracker.record(3.14)
        p = tracker.percentiles()
        assert p["p50"] == pytest.approx(3.14)


class TestLatencyTrackerMaybeLog:
    def test_maybe_log_no_log_before_interval(self):
        tracker = LatencyTracker(log_interval_sec=100.0)
        tracker.record(10.0)
        # Не должно падать даже без лога
        tracker.maybe_log()

    def test_maybe_log_fires_after_interval(self, monkeypatch):
        tracker = LatencyTracker(log_interval_sec=0.0)
        tracker.record(10.0)
        # Устанавливаем _last_log_time в прошлое
        tracker._last_log_time = time.time() - 1
        # Не должно бросать исключение
        tracker.maybe_log()
        # После вызова _last_log_time обновляется
        assert tracker._last_log_time >= time.time() - 0.1
