# -*- coding: utf-8 -*-
"""Тесты StatsAdapter (регистрация команд CommandManager)."""
from unittest.mock import MagicMock

import pytest

from .. import StatsManager
from ..adapters.stats_adapter import StatsAdapter


@pytest.fixture
def stats_manager():
    mgr = StatsManager(manager_name="AdapterTest", config={"enable_logging": False})
    mgr.initialize()
    yield mgr
    mgr.shutdown()


class TestStatsAdapter:
    def test_setup_registers_commands(self, stats_manager):
        mock_process = MagicMock()
        mock_process.command_manager = MagicMock()
        adapter = StatsAdapter(stats_manager, process=mock_process)
        assert adapter.setup() is True
        assert mock_process.command_manager.register_command.call_count == 5

    def test_setup_without_process_returns_false(self, stats_manager):
        adapter = StatsAdapter(stats_manager, process=None)
        assert adapter.setup() is False

    def test_setup_without_command_manager_returns_false(self, stats_manager):
        class ProcessNoCommandManager:
            pass

        adapter = StatsAdapter(stats_manager, process=ProcessNoCommandManager())
        assert adapter.setup() is False

    def test_is_initialized_after_setup(self, stats_manager):
        adapter = StatsAdapter(stats_manager, process=None)
        assert adapter.is_initialized() is False
        mock_process = MagicMock()
        mock_process.command_manager = MagicMock()
        adapter2 = StatsAdapter(stats_manager, process=mock_process)
        assert adapter2.is_initialized() is False
        assert adapter2.setup() is True
        assert adapter2.is_initialized() is True
