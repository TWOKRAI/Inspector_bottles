# -*- coding: utf-8 -*-
"""
Тесты для StatsManagerConfig.
"""

from .. import StatsManagerConfig


class TestStatsManagerConfig:
    """Тесты StatsManagerConfig."""

    def test_default_values(self):
        """Значения по умолчанию."""
        cfg = StatsManagerConfig()
        assert cfg.manager_name == "StatsManager"
        assert cfg.aggregation_interval == 5.0
        assert cfg.flush_interval == 10.0
        assert cfg.enable_logging is True
        assert cfg.log_level == "INFO"

    def test_build(self):
        """Метод build()."""
        cfg = StatsManagerConfig()
        name, d = cfg.build()
        assert name == "StatsManager"
        assert isinstance(d, dict)
        assert d["manager_name"] == "StatsManager"
        assert "channels" in d
        assert "flush_interval" in d
