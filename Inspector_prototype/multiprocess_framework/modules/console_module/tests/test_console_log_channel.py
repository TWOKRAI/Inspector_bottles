"""
Тесты для ConsoleLogChannel.
"""
from unittest.mock import MagicMock

import pytest

from ..channels.console_log_channel import ConsoleLogChannel


def _make_channel():
    mock_console = MagicMock()
    mock_console.write.return_value = True
    return ConsoleLogChannel(mock_console, name="test_channel"), mock_console


class TestConsoleLogChannel:
    def test_properties(self):
        ch, _ = _make_channel()
        assert ch.name == "test_channel"
        assert ch.channel_type == "console_managed"

    def test_write_record(self):
        ch, mock_console = _make_channel()
        record = {"level": "INFO", "message": "hello", "module": "mod"}
        result = ch.write(record)
        assert result["status"] == "success"
        mock_console.write.assert_called_once()
        text = mock_console.write.call_args[0][0]
        assert "hello" in text
        assert "mod" in text

    def test_write_empty_module(self):
        ch, mock_console = _make_channel()
        record = {"level": "ERROR", "message": "boom"}
        result = ch.write(record)
        assert result["status"] == "success"
        text = mock_console.write.call_args[0][0]
        assert "boom" in text

    def test_write_skipped_when_closed(self):
        ch, mock_console = _make_channel()
        ch.close()
        result = ch.write({"level": "INFO", "message": "x"})
        assert result["status"] == "skipped"
        mock_console.write.assert_not_called()

    def test_get_info(self):
        ch, _ = _make_channel()
        info = ch.get_info()
        assert info["name"] == "test_channel"
        assert info["active"] is True
        ch.close()
        assert ch.get_info()["active"] is False
