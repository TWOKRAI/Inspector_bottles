# -*- coding: utf-8 -*-
"""
Тесты ChannelRegistry.

Проверяет: регистрацию, удаление, thread-safety, get/all/names/snapshot/clear.
"""

import threading
from typing import Any, Dict

from ..interfaces import IChannel
from ..core.channel_registry import ChannelRegistry


# ---------------------------------------------------------------------------
# Fixtures / Helpers
# ---------------------------------------------------------------------------


class _MockChannel(IChannel):
    """Минимальный канал для тестов."""

    def __init__(self, name: str, channel_type: str = "mock") -> None:
        self._name = name
        self._type = channel_type
        self.written: list = []
        self.closed = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def channel_type(self) -> str:
        return self._type

    def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
        self.written.append(data)
        return {"status": "success", "channel": self._name}

    def close(self) -> None:
        self.closed = True


def _make_registry() -> ChannelRegistry:
    warnings, errors, debugs = [], [], []
    return ChannelRegistry(
        log_warning=warnings.append,
        log_error=errors.append,
        log_debug=debugs.append,
    )


# ---------------------------------------------------------------------------
# Tests: registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_register_valid_channel(self):
        reg = _make_registry()
        ch = _MockChannel("test")
        assert reg.register(ch) is True
        assert "test" in reg

    def test_register_invalid_object(self):
        reg = _make_registry()
        assert reg.register("not_a_channel") is False  # type: ignore

    def test_register_duplicate_replaces(self):
        reg = _make_registry()
        ch1 = _MockChannel("ch")
        ch2 = _MockChannel("ch", channel_type="file")
        reg.register(ch1)
        reg.register(ch2)
        assert reg.get("ch") is ch2

    def test_unregister_existing(self):
        reg = _make_registry()
        reg.register(_MockChannel("x"))
        assert reg.unregister("x") is True
        assert "x" not in reg

    def test_unregister_missing(self):
        reg = _make_registry()
        assert reg.unregister("nonexistent") is False

    def test_len(self):
        reg = _make_registry()
        assert len(reg) == 0
        reg.register(_MockChannel("a"))
        reg.register(_MockChannel("b"))
        assert len(reg) == 2

    def test_contains(self):
        reg = _make_registry()
        reg.register(_MockChannel("exists"))
        assert "exists" in reg
        assert "missing" not in reg


# ---------------------------------------------------------------------------
# Tests: access
# ---------------------------------------------------------------------------


class TestAccess:
    def test_get_existing(self):
        reg = _make_registry()
        ch = _MockChannel("ch")
        reg.register(ch)
        assert reg.get("ch") is ch

    def test_get_missing_returns_none(self):
        reg = _make_registry()
        assert reg.get("nope") is None

    def test_all_returns_list(self):
        reg = _make_registry()
        reg.register(_MockChannel("a"))
        reg.register(_MockChannel("b"))
        names = {ch.name for ch in reg.all()}
        assert names == {"a", "b"}

    def test_names(self):
        reg = _make_registry()
        reg.register(_MockChannel("x"))
        reg.register(_MockChannel("y"))
        assert set(reg.names()) == {"x", "y"}

    def test_snapshot_is_copy(self):
        reg = _make_registry()
        reg.register(_MockChannel("a"))
        snap = reg.snapshot()
        reg.register(_MockChannel("b"))
        assert "b" not in snap  # snapshot is independent copy

    def test_clear_returns_channels(self):
        reg = _make_registry()
        ch_a = _MockChannel("a")
        ch_b = _MockChannel("b")
        reg.register(ch_a)
        reg.register(ch_b)
        removed = reg.clear()
        assert len(removed) == 2
        assert len(reg) == 0

    def test_get_info(self):
        reg = _make_registry()
        reg.register(_MockChannel("a"))
        info = reg.get_info()
        assert "a" in info
        assert info["a"]["name"] == "a"


# ---------------------------------------------------------------------------
# Tests: thread-safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_register(self):
        reg = _make_registry()
        errors: list = []

        def _register(i: int) -> None:
            try:
                reg.register(_MockChannel(f"ch_{i}"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_register, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(reg) == 50

    def test_concurrent_read_write(self):
        reg = _make_registry()
        for i in range(10):
            reg.register(_MockChannel(f"init_{i}"))

        stop = threading.Event()
        errors: list = []

        def _reader() -> None:
            while not stop.is_set():
                try:
                    reg.all()
                    reg.names()
                    reg.snapshot()
                except Exception as e:
                    errors.append(e)

        def _writer() -> None:
            for i in range(20):
                try:
                    reg.register(_MockChannel(f"dyn_{i}"))
                except Exception as e:
                    errors.append(e)

        readers = [threading.Thread(target=_reader) for _ in range(3)]
        writer = threading.Thread(target=_writer)

        for r in readers:
            r.start()
        writer.start()
        writer.join()
        stop.set()
        for r in readers:
            r.join()

        assert not errors
