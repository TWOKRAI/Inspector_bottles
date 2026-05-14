"""
Тесты для ConsoleRedirector.
"""

import sys
from unittest.mock import MagicMock


from ..redirectors.console_redirector import ConsoleRedirector


def _make_redirector():
    mock_console = MagicMock()
    mock_console.write.return_value = True
    return ConsoleRedirector(mock_console), mock_console


class TestConsoleRedirector:
    def setup_method(self):
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr

    def teardown_method(self):
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr

    def test_write_calls_console_manager(self):
        rd, mock_console = _make_redirector()
        rd.write("hello\n")
        mock_console.write.assert_called_once_with("hello\n", level="STDOUT")

    def test_write_empty_no_call(self):
        rd, mock_console = _make_redirector()
        rd.write("")
        mock_console.write.assert_not_called()

    def test_write_bytes(self):
        rd, mock_console = _make_redirector()
        rd.write(b"bytes data")  # type: ignore[arg-type]
        mock_console.write.assert_called_once()
        text = mock_console.write.call_args[0][0]
        assert "bytes data" in text

    def test_write_after_close_no_call(self):
        rd, mock_console = _make_redirector()
        rd.close()
        rd.write("after close")
        mock_console.write.assert_not_called()

    def test_restore_recovers_stdout(self):
        rd, _ = _make_redirector()
        sys.stdout = rd  # type: ignore[assignment]
        sys.stderr = rd  # type: ignore[assignment]
        assert rd.restore() is True
        assert sys.stdout is self._orig_stdout
        assert sys.stderr is self._orig_stderr

    def test_flush_does_not_raise(self):
        rd, _ = _make_redirector()
        rd.flush()  # should not raise

    def test_isatty_false(self):
        rd, _ = _make_redirector()
        assert rd.isatty() is False

    def test_encoding_property(self):
        rd, _ = _make_redirector()
        assert isinstance(rd.encoding, str)
