# -*- coding: utf-8 -*-
"""
Тесты BoundedChannel: write/drain, политики переполнения, счётчик потерь,
non-destructive get_info (monitor-plane), thread-safety.
"""

import threading

import pytest

from ..observability.bounded_channel import DROP_NEWEST, DROP_OLDEST, BoundedChannel


class TestBasics:
    def test_write_then_drain_returns_records_in_order(self):
        ch = BoundedChannel("t", capacity=10)
        ch.write({"n": 1})
        ch.write({"n": 2})
        assert ch.drain() == [{"n": 1}, {"n": 2}]

    def test_drain_empties(self):
        ch = BoundedChannel("t", capacity=10)
        ch.write({"n": 1})
        ch.drain()
        assert ch.drain() == []
        assert len(ch) == 0

    def test_write_returns_status(self):
        ch = BoundedChannel("t", capacity=10)
        res = ch.write({"n": 1})
        assert res["status"] == "success"
        assert res["channel"] == "t"
        assert res["dropped"] == 0

    def test_name_and_type(self):
        ch = BoundedChannel("worker.log", capacity=5)
        assert ch.name == "worker.log"
        assert ch.channel_type == "memory"


class TestOverflow:
    def test_drop_oldest_keeps_newest_and_counts(self):
        ch = BoundedChannel("t", capacity=3, overflow=DROP_OLDEST)
        for i in range(5):
            ch.write({"n": i})
        assert [r["n"] for r in ch.drain()] == [2, 3, 4]  # старейшие 0,1 вытеснены
        assert ch.dropped == 2

    def test_drop_newest_keeps_oldest_and_counts(self):
        ch = BoundedChannel("t", capacity=3, overflow=DROP_NEWEST)
        for i in range(5):
            ch.write({"n": i})
        assert [r["n"] for r in ch.drain()] == [0, 1, 2]  # новые 3,4 отброшены
        assert ch.dropped == 2

    def test_drop_newest_write_returns_dropped_status(self):
        ch = BoundedChannel("t", capacity=1, overflow=DROP_NEWEST)
        ch.write({"n": 0})
        res = ch.write({"n": 1})
        assert res["status"] == "dropped"

    def test_no_drop_under_capacity(self):
        ch = BoundedChannel("t", capacity=3)
        ch.write({})
        ch.write({})
        assert ch.dropped == 0


class TestValidation:
    def test_invalid_capacity_raises(self):
        with pytest.raises(ValueError):
            BoundedChannel("t", capacity=0)

    def test_invalid_overflow_raises(self):
        with pytest.raises(ValueError):
            BoundedChannel("t", capacity=1, overflow="explode")


class TestMonitorPlane:
    def test_get_info_is_non_destructive(self):
        ch = BoundedChannel("t", capacity=5)
        ch.write({"n": 1})
        ch.write({"n": 2})
        info = ch.get_info()
        assert info["depth"] == 2
        assert info["capacity"] == 5
        assert info["dropped"] == 0
        assert info["written"] == 2
        assert info["overflow"] == DROP_OLDEST
        # мониторинг НЕ опустошает канал — записи остаются для владельца
        assert len(ch) == 2


class TestThreadSafety:
    def test_concurrent_writes_no_loss(self):
        ch = BoundedChannel("t", capacity=100_000)

        def writer():
            for i in range(1000):
                ch.write({"i": i})

        threads = [threading.Thread(target=writer) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(ch.drain()) == 8000
        assert ch.dropped == 0
