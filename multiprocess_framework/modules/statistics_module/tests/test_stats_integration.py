# -*- coding: utf-8 -*-
"""Интеграционные тесты каналов, get_metric с тегами, thread-safety."""

import json
import threading
from unittest.mock import MagicMock


from .. import StatsManager
from ..channels.file_stats_channel import FileStatsChannel
from ..channels.log_stats_channel import LogStatsChannel


class TestFileStatsChannelIntegration:
    def test_write_to_real_file(self, tmp_path):
        path = tmp_path / "metrics.jsonl"
        ch = FileStatsChannel(file_path=str(path))
        payload = {
            "timestamp": 1.0,
            "total_count": 1,
            "metrics": [{"name": "x", "type": "counter", "count": 5}],
        }
        result = ch.write(payload)
        assert result["status"] == "success"
        assert path.is_file()
        content = path.read_text(encoding="utf-8")
        row = json.loads(content.strip())
        assert row["metrics"][0]["count"] == 5

    def test_write_csv_format(self, tmp_path):
        path = tmp_path / "metrics.csv"
        ch = FileStatsChannel(file_path=str(path), format="csv")
        payload = {
            "timestamp": 42.0,
            "total_count": 2,
            "metrics": [{"name": "a", "type": "gauge", "value": 3.0}],
        }
        assert ch.write(payload)["status"] == "success"
        line = path.read_text(encoding="utf-8").strip()
        assert line.startswith("42.0,2,")
        assert '"name": "a"' in line or "'name': 'a'" in line or "a" in line

    def test_write_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "deep" / "nested" / "metrics.jsonl"
        ch = FileStatsChannel(file_path=str(path))
        assert ch.write({"timestamp": 0.0, "total_count": 0, "metrics": []})["status"] == "success"
        assert path.is_file()
        assert path.parent.is_dir()


class TestLogStatsChannelIntegration:
    def test_write_calls_performance(self):
        mock_logger = MagicMock()
        ch = LogStatsChannel(logger_manager=mock_logger)
        data = {"timestamp": 100.0, "total_count": 1, "metrics": [{"name": "m"}]}
        assert ch.write(data)["status"] == "success"
        mock_logger.performance.assert_called_once()

    def test_write_without_logger_returns_error(self):
        ch = LogStatsChannel(logger_manager=None)
        result = ch.write({"timestamp": 0.0, "total_count": 0, "metrics": []})
        assert result["status"] == "error"


class TestGetMetricWithTags:
    def setup_method(self):
        self.mgr = StatsManager(
            manager_name="TagTestStats",
            config={"enable_logging": False},
        )
        self.mgr.initialize()

    def teardown_method(self):
        self.mgr.shutdown()

    def test_get_metric_returns_first_match_ignoring_tags(self):
        self.mgr.increment("x", tags={"region": "eu"})
        self.mgr.increment("x", tags={"region": "us"})
        first = self.mgr.get_metric("x")
        assert first is not None
        assert first["name"] == "x"
        assert first["count"] == 1.0
        assert first["tags"]["region"] == "eu"
        all_m = self.mgr.get_all_metrics()
        assert len(all_m) == 2

    def test_get_metric_missing_returns_none(self):
        assert self.mgr.get_metric("nonexistent") is None


class TestThreadSafety:
    def setup_method(self):
        self.mgr = StatsManager(
            manager_name="ThreadStats",
            config={"enable_logging": False},
        )
        self.mgr.initialize()

    def teardown_method(self):
        self.mgr.shutdown()

    def test_concurrent_record_metric(self):
        def worker():
            for _ in range(100):
                self.mgr.record_metric("ops", 1)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        m = self.mgr.get_metric("ops")
        assert m is not None
        assert m["count"] == 1000.0

    def test_concurrent_mixed_operations(self):
        errors = []

        def record_worker():
            try:
                for _ in range(50):
                    self.mgr.record_metric("mix", 1)
            except Exception as e:
                errors.append(e)

        def read_worker():
            try:
                for _ in range(50):
                    _ = self.mgr.get_all_metrics()
            except Exception as e:
                errors.append(e)

        threads = []
        for _ in range(5):
            threads.append(threading.Thread(target=record_worker))
        for _ in range(5):
            threads.append(threading.Thread(target=read_worker))
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
