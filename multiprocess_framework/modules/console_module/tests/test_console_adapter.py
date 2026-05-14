"""
Тесты для ConsoleAdapter.
"""

from unittest.mock import MagicMock, patch


from ..adapters.console_adapter import ConsoleAdapter
from ..configs.console_config import ConsoleConfig
from ..core.console_manager import ConsoleManager


def _make_adapter(enabled=False, interactive=False):
    cfg = ConsoleConfig(enabled=enabled, interactive=interactive)
    mgr = ConsoleManager(manager_name="test", config=cfg)
    mgr.initialize()

    process = MagicMock()
    process.name = "test_process"
    process.logger_manager = MagicMock()
    process.logger_manager.register_channel = MagicMock()
    process.command_manager = MagicMock()
    process.command_manager.handle_command = MagicMock()

    adapter = ConsoleAdapter(mgr, process=process)
    return adapter, mgr, process


class TestConsoleAdapter:
    def test_setup_returns_true_disabled(self):
        adapter, mgr, _ = _make_adapter(enabled=False)
        assert adapter.setup() is True
        assert adapter.is_initialized() is True

    def test_setup_registers_log_channel_when_enabled(self):
        adapter, mgr, process = _make_adapter(enabled=True)
        adapter.setup()
        process.logger_manager.register_channel.assert_called_once()

    def test_setup_no_log_channel_when_disabled(self):
        adapter, mgr, process = _make_adapter(enabled=False)
        adapter.setup()
        process.logger_manager.register_channel.assert_not_called()

    def test_setup_starts_input_loop_when_interactive(self):
        adapter, mgr, process = _make_adapter(enabled=True, interactive=True)
        with patch.object(mgr, "enable_input") as mock_enable:
            adapter.setup()
            mock_enable.assert_called_once()

    def test_setup_no_input_when_not_interactive(self):
        adapter, mgr, process = _make_adapter(enabled=True, interactive=False)
        with patch.object(mgr, "enable_input") as mock_enable:
            adapter.setup()
            mock_enable.assert_not_called()

    def test_is_initialized_false_before_setup(self):
        cfg = ConsoleConfig()
        mgr = ConsoleManager(config=cfg)
        adapter = ConsoleAdapter(mgr)
        assert adapter.is_initialized() is False
