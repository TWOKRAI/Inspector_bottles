"""
Тесты для ConsoleManager.

pytest -q Inspector_prototype/multiprocess_framework/modules/console_module/tests/
"""
import sys
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from ..configs.console_config import ConsoleConfig
from ..core.console_manager import ConsoleManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_manager(enabled=False, interactive=False, redirect_stdout=False):
    cfg = ConsoleConfig(
        enabled=enabled,
        interactive=interactive,
        redirect_stdout=redirect_stdout,
    )
    return ConsoleManager(manager_name="test_console", config=cfg)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

class TestLifecycle:
    def test_initialize_default(self):
        mgr = _make_manager()
        assert mgr.initialize() is True
        assert mgr.is_initialized is True

    def test_shutdown_after_initialize(self):
        mgr = _make_manager()
        mgr.initialize()
        assert mgr.shutdown() is True
        assert mgr.is_initialized is False

    def test_initialize_enabled(self):
        mgr = _make_manager(enabled=True)
        with patch.object(mgr._platform, "create", return_value=True) as mock_create, \
             patch.object(mgr._platform, "show", return_value=True):
            assert mgr.initialize() is True
            mock_create.assert_called_once()


# ---------------------------------------------------------------------------
# write / show / hide
# ---------------------------------------------------------------------------

class TestWrite:
    def test_write_calls_platform(self):
        mgr = _make_manager()
        mgr.initialize()
        with patch.object(mgr._platform, "write", return_value=True) as mock_write:
            result = mgr.write("hello\n")
            assert result is True
            mock_write.assert_called_once_with("hello\n")

    def test_show_delegates_to_platform(self):
        mgr = _make_manager()
        mgr.initialize()
        with patch.object(mgr._platform, "show", return_value=True) as mock_show:
            assert mgr.show() is True
            mock_show.assert_called_once()

    def test_hide_delegates_to_platform(self):
        mgr = _make_manager()
        mgr.initialize()
        with patch.object(mgr._platform, "hide", return_value=True) as mock_hide:
            assert mgr.hide() is True
            mock_hide.assert_called_once()

    def test_is_visible(self):
        mgr = _make_manager()
        mgr.initialize()
        with patch.object(mgr._platform, "is_visible", return_value=True):
            assert mgr.is_visible() is True


# ---------------------------------------------------------------------------
# create_console / close_console / list_consoles
# ---------------------------------------------------------------------------

class TestMultipleConsoles:
    def test_create_console_not_supported(self):
        mgr = _make_manager()
        mgr.initialize()
        with patch.object(mgr._platform, "supports_multiple_windows", return_value=False):
            assert mgr.create_console("extra") is False
        assert mgr.list_consoles() == []

    def test_create_console_supported(self):
        mgr = _make_manager()
        mgr.initialize()
        with patch.object(mgr._platform, "supports_multiple_windows", return_value=True):
            with patch("multiprocess_framework.modules.console_module.core.console_manager.create_platform_console") as mock_factory:
                fake_console = MagicMock()
                fake_console.create.return_value = True
                mock_factory.return_value = fake_console
                result = mgr.create_console("extra", title="Extra")
                assert result is True
                assert "extra" in mgr.list_consoles()

    def test_close_console_unknown(self):
        mgr = _make_manager()
        mgr.initialize()
        assert mgr.close_console("nonexistent") is False

    def test_write_to_named_console(self):
        mgr = _make_manager()
        mgr.initialize()
        fake_console = MagicMock()
        fake_console.write.return_value = True
        mgr._consoles["secondary"] = fake_console
        result = mgr.write("msg", console_name="secondary")
        assert result is True
        fake_console.write.assert_called_once_with("msg")


# ---------------------------------------------------------------------------
# enable_input / disable_input
# ---------------------------------------------------------------------------

class TestInputLoop:
    def test_enable_input_starts_thread(self):
        mgr = _make_manager()
        mgr.initialize()
        called = []

        with patch.object(mgr._platform, "read_input", side_effect=["line1", None]):
            mgr.enable_input(lambda line: called.append(line))
            time.sleep(0.1)
            mgr.disable_input()

        assert "line1" in called

    def test_disable_input_stops_thread(self):
        mgr = _make_manager()
        mgr.initialize()
        with patch.object(mgr._platform, "read_input", return_value=None):
            mgr.enable_input(lambda line: None)
            mgr.disable_input()
            assert mgr._input_thread_running is False

    def test_double_enable_is_idempotent(self):
        """Повторный вызов enable_input пока уже запущен — не создаёт новый поток."""
        mgr = _make_manager()
        mgr.initialize()

        import threading
        stop_event = threading.Event()

        def blocking_read():
            stop_event.wait()  # блокируем до явного сигнала
            return None

        with patch.object(mgr._platform, "read_input", side_effect=blocking_read):
            mgr.enable_input(lambda line: None)
            assert mgr._input_thread_running is True
            first_was_running = mgr._input_thread_running
            # Повторный вызов — должен вернуть True без создания нового потока
            result = mgr.enable_input(lambda line: None)
            assert result is True
            assert first_was_running is True
            stop_event.set()
            mgr.disable_input()


# ---------------------------------------------------------------------------
# setup_redirect
# ---------------------------------------------------------------------------

class TestRedirect:
    def setup_method(self):
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr

    def teardown_method(self):
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr

    def test_redirect_enable_disable(self):
        mgr = _make_manager()
        mgr.initialize()
        assert mgr.setup_redirect(True) is True
        assert mgr._redirector is not None
        assert mgr.setup_redirect(False) is True
        assert mgr._redirector is None

    def test_redirect_idempotent(self):
        mgr = _make_manager()
        mgr.initialize()
        mgr.setup_redirect(True)
        redirector_first = mgr._redirector
        mgr.setup_redirect(True)
        assert mgr._redirector is redirector_first
        mgr.setup_redirect(False)

    def test_shutdown_restores_stdout(self):
        mgr = _make_manager()
        mgr.initialize()
        mgr.setup_redirect(True)
        mgr.shutdown()
        assert sys.stdout is self._orig_stdout


# ---------------------------------------------------------------------------
# get_stats / get_debug_info
# ---------------------------------------------------------------------------

class TestStats:
    def test_get_stats_keys(self):
        mgr = _make_manager()
        mgr.initialize()
        stats = mgr.get_stats()
        assert "enabled" in stats
        assert "visible" in stats
        assert "consoles" in stats
        mgr.shutdown()

    def test_get_debug_info(self):
        mgr = _make_manager()
        mgr.initialize()
        info = mgr.get_debug_info()
        assert "manager_name" in info
        assert "platform" in info
        mgr.shutdown()
