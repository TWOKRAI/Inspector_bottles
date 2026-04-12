"""
Тесты для платформенных реализаций IPlatformConsole.

Проверяем текущую платформу через фабрику.
"""
import sys
from unittest.mock import MagicMock, patch

import pytest

from ..platforms import create_platform_console
from ..interfaces import IPlatformConsole
from ..platforms.windows import WindowsConsole


class TestCurrentPlatformConsole:
    def setup_method(self):
        self.console = create_platform_console()

    def teardown_method(self):
        self.console.close()

    def test_isinstance(self):
        assert isinstance(self.console, IPlatformConsole)

    def test_create(self):
        result = self.console.create("test title")
        assert isinstance(result, bool)

    def test_write(self):
        self.console.create("test")
        result = self.console.write("hello pytest\n")
        assert isinstance(result, bool)

    def test_show_hide(self):
        self.console.create("test")
        assert isinstance(self.console.show(), bool)
        assert isinstance(self.console.hide(), bool)
        # После hide is_visible должен вернуть False (на платформах без нативного API)
        self.console.show()

    def test_is_visible(self):
        self.console.create("test")
        assert isinstance(self.console.is_visible(), bool)

    def test_supports_multiple_windows(self):
        result = self.console.supports_multiple_windows()
        assert isinstance(result, bool)

    def test_read_input_returns_none_on_eof(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda: (_ for _ in ()).throw(EOFError()))
        result = self.console.read_input()
        assert result is None

    def test_close_does_not_raise(self):
        self.console.create("test")
        self.console.close()


def _make_ctypes_mock(hwnd: int) -> MagicMock:
    """Создаёт mock ctypes с kernel32 и user32."""
    ctypes_mock = MagicMock()
    kernel32 = MagicMock()
    user32 = MagicMock()

    kernel32.GetConsoleWindow.return_value = hwnd
    kernel32.AllocConsole.return_value = 1
    kernel32.FreeConsole.return_value = 1
    kernel32.SetConsoleTitleW.return_value = 1
    kernel32.GetStdHandle.return_value = MagicMock()
    kernel32.WriteConsoleW.return_value = 1
    user32.ShowWindow.return_value = 1

    ctypes_mock.windll.kernel32 = kernel32
    ctypes_mock.windll.user32 = user32
    return ctypes_mock


def _patch_ctypes(hwnd: int):
    """Патчит ctypes в sys.modules, чтобы перехватить локальные `import ctypes`."""
    ctypes_mock = _make_ctypes_mock(hwnd)
    return patch.dict("sys.modules", {"ctypes": ctypes_mock}), ctypes_mock


class TestWindowsConsoleMocked:
    """Mock-based тесты для WindowsConsole. Работают на любой платформе."""

    def test_create_allocates_console_when_no_existing(self):
        """hwnd=0 → AllocConsole вызван, _allocated_console=True."""
        patcher, ctypes_mock = _patch_ctypes(hwnd=0)
        with patcher:
            console = WindowsConsole()
            result = console.create("Test")

        assert result is True
        assert console._allocated_console is True
        ctypes_mock.windll.kernel32.AllocConsole.assert_called_once()

    def test_create_uses_existing_console(self):
        """hwnd != 0 → AllocConsole НЕ вызван, _allocated_console=False."""
        patcher, ctypes_mock = _patch_ctypes(hwnd=12345)
        with patcher:
            console = WindowsConsole()
            result = console.create("Test")

        assert result is True
        assert console._allocated_console is False
        ctypes_mock.windll.kernel32.AllocConsole.assert_not_called()

    def test_show_calls_show_window(self):
        """show() вызывает ShowWindow(hwnd, 5)."""
        hwnd = 999
        patcher, ctypes_mock = _patch_ctypes(hwnd=hwnd)
        with patcher:
            console = WindowsConsole()
            result = console.show()

        assert result is True
        ctypes_mock.windll.user32.ShowWindow.assert_called_once_with(hwnd, 5)

    def test_hide_calls_show_window(self):
        """hide() вызывает ShowWindow(hwnd, 0)."""
        hwnd = 888
        patcher, ctypes_mock = _patch_ctypes(hwnd=hwnd)
        with patcher:
            console = WindowsConsole()
            result = console.hide()

        assert result is True
        ctypes_mock.windll.user32.ShowWindow.assert_called_once_with(hwnd, 0)

    def test_close_frees_allocated_console(self):
        """_allocated_console=True → FreeConsole вызван."""
        patcher, ctypes_mock = _patch_ctypes(hwnd=0)
        with patcher:
            console = WindowsConsole()
            console._allocated_console = True
            console.close()

        ctypes_mock.windll.kernel32.FreeConsole.assert_called_once()
        assert console._allocated_console is False

    def test_close_skips_free_when_not_allocated(self):
        """_allocated_console=False → FreeConsole НЕ вызван."""
        patcher, ctypes_mock = _patch_ctypes(hwnd=12345)
        with patcher:
            console = WindowsConsole()
            console._allocated_console = False
            console.close()

        ctypes_mock.windll.kernel32.FreeConsole.assert_not_called()

    def test_write_calls_write_console(self):
        """write() делегирует вывод sys.stdout."""
        console = WindowsConsole()
        console._created = True
        console._visible = True

        mock_stdout = MagicMock()
        with patch("sys.stdout", mock_stdout):
            result = console.write("hello\n")

        assert result is True
        mock_stdout.write.assert_called_once_with("hello\n")
        mock_stdout.flush.assert_called_once()

    def test_set_title(self):
        """create() вызывает SetConsoleTitleW с переданным заголовком."""
        patcher, ctypes_mock = _patch_ctypes(hwnd=0)
        with patcher:
            console = WindowsConsole()
            console.create("My Title")

        ctypes_mock.windll.kernel32.SetConsoleTitleW.assert_called_with("My Title")
