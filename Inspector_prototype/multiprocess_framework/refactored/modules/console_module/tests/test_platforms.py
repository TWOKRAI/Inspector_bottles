"""
Тесты для платформенных реализаций IPlatformConsole.

Проверяем текущую платформу через фабрику.
"""
import sys

import pytest

from ..platforms import create_platform_console
from ..interfaces import IPlatformConsole


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
