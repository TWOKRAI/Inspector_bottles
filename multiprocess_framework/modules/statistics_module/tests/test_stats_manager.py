# -*- coding: utf-8 -*-
"""Тесты StatsManager."""

from .. import StatsManager, StatsManagerConfig, IStatsManager
from ...channel_routing_module.interfaces import IChannelRoutingManager


class TestStatsManagerCreation:
    def test_create_manager(self):
        mgr = StatsManager(manager_name="TestStats", config={})
        assert mgr.manager_name == "TestStats"
        assert isinstance(mgr, IStatsManager)
        assert isinstance(mgr, IChannelRoutingManager)

    def test_initialize(self):
        mgr = StatsManager(manager_name="TestStats", config={"enable_logging": False})
        result = mgr.initialize()
        assert result is True
        assert mgr.is_initialized is True

    def test_initialize_with_config_object(self):
        cfg = StatsManagerConfig()
        cfg.manager_name = "TestStats2"
        cfg.enable_logging = False
        mgr = StatsManager(config=cfg)
        assert mgr.initialize() is True

    def test_shutdown(self):
        mgr = StatsManager(manager_name="TestStats", config={"enable_logging": False})
        mgr.initialize()
        mgr.increment("x")
        result = mgr.shutdown()
        assert result is True
        assert mgr.is_initialized is False


class TestMetricTypes:
    def setup_method(self):
        self.mgr = StatsManager(
            manager_name="TestStats",
            config={"enable_logging": False},
        )
        self.mgr.initialize()

    def teardown_method(self):
        self.mgr.shutdown()

    def test_record_metric_counter(self):
        self.mgr.record_metric("ops.count", 5)
        m = self.mgr.get_metric("ops.count")
        assert m is not None
        assert m["type"] == "counter"
        assert m["count"] == 5.0

    def test_increment(self):
        self.mgr.increment("ops.count")
        self.mgr.increment("ops.count")
        self.mgr.increment("ops.count")
        m = self.mgr.get_metric("ops.count")
        assert m["count"] == 3.0

    def test_record_timing(self):
        self.mgr.record_timing("req.duration", 0.5)
        self.mgr.record_timing("req.duration", 1.0)
        m = self.mgr.get_metric("req.duration")
        assert m is not None
        assert m["type"] == "timing"
        assert m["count"] == 2
        assert m["min"] == 0.5
        assert m["max"] == 1.0
        assert m["avg"] == 0.75

    def test_gauge(self):
        self.mgr.gauge("mem.used", 1024.0)
        self.mgr.gauge("mem.used", 2048.0)
        m = self.mgr.get_metric("mem.used")
        assert m is not None
        assert m["type"] == "gauge"
        assert m["value"] == 2048.0  # последнее значение

    def test_histogram(self):
        for v in [1.0, 2.0, 3.0, 4.0, 5.0]:
            self.mgr.histogram("req.size", v)
        m = self.mgr.get_metric("req.size")
        assert m is not None
        assert m["type"] == "histogram"
        assert m["count"] == 5
        assert m["min"] == 1.0
        assert m["max"] == 5.0

    def test_get_all_metrics(self):
        self.mgr.increment("a")
        self.mgr.gauge("b", 1.0)
        self.mgr.record_timing("c", 0.1)
        all_m = self.mgr.get_all_metrics()
        assert len(all_m) == 3

    def test_reset_metrics(self):
        self.mgr.increment("x")
        self.mgr.gauge("y", 1.0)
        assert len(self.mgr.get_all_metrics()) == 2
        self.mgr.reset_metrics()
        assert len(self.mgr.get_all_metrics()) == 0


class TestTagsMerge:
    """Проверяем корректный merge тегов: user tags приоритетнее default_tags."""

    def test_default_tags_applied(self):
        mgr = StatsManager(
            manager_name="TestStats",
            config={"enable_logging": False, "default_tags": {"env": "test"}},
        )
        mgr.initialize()
        mgr.increment("x")
        m = mgr.get_metric("x")
        assert m["tags"]["env"] == "test"
        mgr.shutdown()

    def test_user_tags_override_default(self):
        mgr = StatsManager(
            manager_name="TestStats",
            config={"enable_logging": False, "default_tags": {"env": "prod"}},
        )
        mgr.initialize()
        mgr.increment("x", tags={"env": "staging"})
        m = mgr.get_metric("x")
        assert m["tags"]["env"] == "staging"  # user tag wins
        mgr.shutdown()

    def test_tags_create_separate_keys(self):
        mgr = StatsManager(
            manager_name="TestStats",
            config={"enable_logging": False},
        )
        mgr.initialize()
        mgr.increment("x", tags={"region": "eu"})
        mgr.increment("x", tags={"region": "us"})
        all_m = mgr.get_all_metrics()
        assert len(all_m) == 2  # две отдельные метрики по тегу
        mgr.shutdown()

    def test_consistent_key_for_same_tags(self):
        mgr = StatsManager(
            manager_name="TestStats",
            config={"enable_logging": False, "default_tags": {"env": "test"}},
        )
        mgr.initialize()
        mgr.record_metric("x", 5, tags={"host": "a"})
        mgr.record_metric("x", 3, tags={"host": "a"})
        all_m = mgr.get_all_metrics()
        assert len(all_m) == 1
        m = next(iter(all_m.values()))
        assert m["count"] == 8.0
        mgr.shutdown()


class TestNoCounting:
    """Проверяем что метрики считаются ОДИН раз (не умножаются на кол-во каналов)."""

    def test_single_count_with_multiple_channels(self):
        from ...channel_routing_module.interfaces import IChannel

        class DummyChannel(IChannel):
            def __init__(self, n):
                self._name = n
                self.received = []

            @property
            def name(self):
                return self._name

            def write(self, data):
                self.received.append(data)
                return {"status": "ok"}

            def close(self):
                pass

        mgr = StatsManager(
            manager_name="TestStats",
            config={"enable_logging": False},
        )
        mgr.initialize()

        ch1 = DummyChannel("ch1")
        ch2 = DummyChannel("ch2")
        mgr.register_channel(ch1)
        mgr.register_channel(ch2)

        mgr.record_metric("ops", 1)
        mgr.record_metric("ops", 1)
        mgr.record_metric("ops", 1)

        mgr.flush()

        # Каждый канал должен получить snapshot с count=3, не 6
        assert len(ch1.received) >= 1
        assert len(ch2.received) >= 1
        metrics_ch1 = ch1.received[0].get("metrics", [])
        if metrics_ch1:
            ops_metric = next((m for m in metrics_ch1 if m["name"] == "ops"), None)
            if ops_metric:
                assert ops_metric["count"] == 3.0, f"Expected 3, got {ops_metric['count']}"

        mgr.shutdown()


class TestFlushAndChannels:
    def test_manual_flush(self):
        """flush() не должен кидать исключений."""
        mgr = StatsManager(
            manager_name="TestStats",
            config={"enable_logging": False},
        )
        mgr.initialize()
        mgr.increment("x")
        mgr.flush()
        mgr.shutdown()

    def test_get_stats_fields(self):
        mgr = StatsManager(
            manager_name="TestStats",
            config={"enable_logging": False},
        )
        mgr.initialize()
        mgr.increment("a")
        stats = mgr.get_stats()
        assert "channel_count" in stats
        assert "metrics_count" in stats
        assert "metric_names" in stats
        assert "buffer" in stats
        mgr.shutdown()

    def test_fallback_channel_registered(self):
        """Если нет каналов в конфиге, должен создаться file_stats fallback."""
        mgr = StatsManager(
            manager_name="TestStats",
            config={"enable_logging": False, "channels": {}},
        )
        mgr.initialize()
        assert len(mgr.get_all_channels()) >= 1
        mgr.shutdown()
