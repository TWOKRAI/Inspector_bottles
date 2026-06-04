# -*- coding: utf-8 -*-
"""
Тесты ChannelRoutingManager.

Проверяет: initialize/shutdown, register_channel, route, register_route,
register_broadcast, buffer integration, get_stats.
"""

import time
from typing import Any, Dict, List

from ..interfaces import IChannel
from ..core.channel_routing_manager import ChannelRoutingManager
from ..buffers.direct_buffer import DirectBuffer
from ..buffers.batch_buffer import BatchBuffer, BatchConfig
from ..buffers.async_sender_buffer import AsyncSenderBuffer


# ---------------------------------------------------------------------------
# Fixtures / Helpers
# ---------------------------------------------------------------------------


class _MockChannel(IChannel):
    def __init__(self, name: str, channel_type: str = "mock") -> None:
        self._name = name
        self._type = channel_type
        self.written: List[Dict[str, Any]] = []
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


class _ConcreteManager(ChannelRoutingManager):
    """Минимальная конкретная реализация для тестов."""

    def __init__(self, **kwargs):
        super().__init__("TestManager", **kwargs)

    def initialize(self) -> bool:
        return super().initialize()

    def shutdown(self) -> bool:
        return super().shutdown()


def _manager(**kwargs) -> _ConcreteManager:
    mgr = _ConcreteManager(**kwargs)
    mgr.initialize()
    return mgr


# ---------------------------------------------------------------------------
# Tests: lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_initialize_sets_flag(self):
        mgr = _ConcreteManager()
        assert not mgr.is_initialized
        mgr.initialize()
        assert mgr.is_initialized

    def test_shutdown_clears_flag(self):
        mgr = _manager()
        mgr.shutdown()
        assert not mgr.is_initialized

    def test_shutdown_closes_channels(self):
        mgr = _manager()
        ch = _MockChannel("ch")
        mgr.register_channel(ch)
        mgr.shutdown()
        assert ch.closed

    def test_initialize_starts_buffer(self):
        received = []
        buf = AsyncSenderBuffer(send_fn=lambda ch, data: received.append(data))
        mgr = _manager(buffer_strategy=buf)
        assert buf.is_alive
        mgr.shutdown()
        assert not buf.is_alive


# ---------------------------------------------------------------------------
# Tests: channel management
# ---------------------------------------------------------------------------


class TestChannelManagement:
    def test_register_channel(self):
        mgr = _manager()
        ch = _MockChannel("ch1")
        assert mgr.register_channel(ch)
        assert mgr.get_channel("ch1") is ch

    def test_register_invalid_channel(self):
        mgr = _manager()
        assert not mgr.register_channel("not_a_channel")  # type: ignore

    def test_unregister_channel(self):
        mgr = _manager()
        mgr.register_channel(_MockChannel("x"))
        assert mgr.unregister_channel("x")
        assert mgr.get_channel("x") is None

    def test_get_all_channels(self):
        mgr = _manager()
        mgr.register_channel(_MockChannel("a"))
        mgr.register_channel(_MockChannel("b"))
        names = {ch.name for ch in mgr.get_all_channels()}
        assert names == {"a", "b"}


# ---------------------------------------------------------------------------
# Tests: routing (no buffer)
# ---------------------------------------------------------------------------


class TestRouting:
    def test_route_to_channel_by_name(self):
        mgr = _manager(dispatcher_key_field="type")
        ch = _MockChannel("console")
        mgr.register_channel(ch)
        # channel name is the default handler key
        result = mgr.route({"type": "console", "msg": "hello"})
        assert result.get("status") == "success"
        assert len(ch.written) == 1

    def test_register_route(self):
        mgr = _manager(dispatcher_key_field="level")
        ch = _MockChannel("file")
        mgr.register_channel(ch)
        assert mgr.register_route("INFO", "file")
        mgr.route({"level": "INFO", "message": "test"})
        assert len(ch.written) == 1

    def test_register_route_missing_channel(self):
        mgr = _manager()
        assert not mgr.register_route("key", "nonexistent")

    def test_route_unknown_key_returns_error_or_unhandled(self):
        mgr = _manager(dispatcher_key_field="type")
        result = mgr.route({"type": "unknown"})
        # Dispatcher returns error dict for unknown key
        assert isinstance(result, dict)

    def test_register_broadcast(self):
        mgr = _manager(dispatcher_key_field="type")
        ch_a = _MockChannel("a")
        ch_b = _MockChannel("b")
        mgr.register_channel(ch_a)
        mgr.register_channel(ch_b)
        assert mgr.register_broadcast("ALL", ["a", "b"])
        mgr.route({"type": "ALL", "data": "x"})
        assert len(ch_a.written) == 1
        assert len(ch_b.written) == 1

    def test_register_broadcast_missing_channel(self):
        mgr = _manager()
        mgr.register_channel(_MockChannel("exists"))
        assert not mgr.register_broadcast("key", ["exists", "missing"])

    def test_custom_key_field_override(self):
        mgr = _manager(dispatcher_key_field="type")
        ch = _MockChannel("console")
        mgr.register_channel(ch)
        mgr.register_route("debug", "console")
        mgr.route({"type": "debug", "msg": "dbg"})
        assert len(ch.written) == 1

    def test_route_key_field_per_call(self):
        mgr = _manager(dispatcher_key_field="type")
        ch = _MockChannel("console")
        mgr.register_channel(ch)
        mgr.register_route("console", "console")
        mgr.route({"type": "wrong", "channel": "console"}, key_field="channel")
        assert len(ch.written) == 1


# ---------------------------------------------------------------------------
# Tests: buffer integration
# ---------------------------------------------------------------------------


class TestBufferIntegration:
    def test_direct_buffer_immediate_write(self):
        written = []
        buf = DirectBuffer(send_fn=lambda ch, data: written.append((ch, data)))
        mgr = _manager(buffer_strategy=buf)
        ch = _MockChannel("ch")
        mgr.register_channel(ch)
        mgr.route({"type": "ch", "x": 1})
        assert len(written) == 1
        assert written[0] == ("ch", {"type": "ch", "x": 1})

    def test_batch_buffer_flush(self):
        flushed = {}

        def _flush(ch, batch):
            flushed.setdefault(ch, []).extend(batch)

        config = BatchConfig(max_size=1000, flush_interval=60.0)
        buf = BatchBuffer(flush_fn=_flush, config=config)
        mgr = _manager(buffer_strategy=buf)
        ch = _MockChannel("ch")
        mgr.register_channel(ch)
        mgr.register_route("INFO", "ch")
        mgr.route({"type": "INFO", "msg": "a"})
        mgr.route({"type": "INFO", "msg": "b"})
        assert len(flushed.get("ch", [])) == 0  # not flushed yet
        mgr.flush()
        assert len(flushed.get("ch", [])) == 2

    def test_async_sender_buffer(self):
        received = []
        buf = AsyncSenderBuffer(send_fn=lambda ch, data: received.append((ch, data)))
        mgr = _manager(buffer_strategy=buf)
        ch = _MockChannel("ch")
        mgr.register_channel(ch)
        mgr.register_route("ev", "ch")
        mgr.route({"type": "ev", "n": 1})
        mgr.route({"type": "ev", "n": 2})
        time.sleep(0.3)
        assert len(received) == 2
        mgr.shutdown()


# ---------------------------------------------------------------------------
# Tests: reconfigure (full-rebuild)
# ---------------------------------------------------------------------------


class _RebuildableManager(ChannelRoutingManager):
    """Наследник с реальным _rebuild_from_config для проверки full-rebuild.

    Конфиг: {"channels": ["a", "b"]} → создаёт по mock-каналу на каждое имя.
    """

    def __init__(self, **kwargs):
        super().__init__("RebuildableManager", **kwargs)

    def _rebuild_from_config(self, config: Dict[str, Any]) -> None:
        for name in config.get("channels", []):
            self.register_channel(_MockChannel(name))


class TestReconfigure:
    def test_base_reconfigure_is_noop_rebuild(self):
        # База: _rebuild_from_config — no-op, каналы только закрываются.
        mgr = _manager()
        ch = _MockChannel("old")
        mgr.register_channel(ch)
        assert mgr.reconfigure({"anything": 1}) is True
        assert ch.closed
        assert mgr.get_all_channels() == []

    def test_reconfigure_rebuilds_channels(self):
        mgr = _RebuildableManager()
        mgr.initialize()
        mgr.register_channel(_MockChannel("legacy"))
        old = mgr.get_channel("legacy")
        assert mgr.reconfigure({"channels": ["a", "b"]}) is True
        assert old.closed
        names = {ch.name for ch in mgr.get_all_channels()}
        assert names == {"a", "b"}

    def test_reconfigure_none_returns_false(self):
        mgr = _manager()
        assert mgr.reconfigure(None) is False

    def test_reconfigure_before_initialize_does_not_raise(self):
        mgr = _RebuildableManager()  # без initialize()
        assert mgr.reconfigure({"channels": ["x"]}) is True
        assert {ch.name for ch in mgr.get_all_channels()} == {"x"}

    def test_reconfigure_idempotent(self):
        mgr = _RebuildableManager()
        mgr.initialize()
        assert mgr.reconfigure({"channels": ["a"]}) is True
        assert mgr.reconfigure({"channels": ["a"]}) is True
        names = [ch.name for ch in mgr.get_all_channels()]
        assert names == ["a"]  # без дублей


# ---------------------------------------------------------------------------
# Tests: stats
# ---------------------------------------------------------------------------


class TestStats:
    def test_stats_includes_channels(self):
        mgr = _manager()
        mgr.register_channel(_MockChannel("a"))
        mgr.register_channel(_MockChannel("b"))
        s = mgr.get_stats()
        assert "channels" in s
        assert set(s["channels"]) == {"a", "b"}
        assert s["channel_count"] == 2

    def test_stats_includes_routing_counters(self):
        mgr = _manager(dispatcher_key_field="type")
        ch = _MockChannel("ch")
        mgr.register_channel(ch)
        mgr.route({"type": "ch"})
        s = mgr.get_stats()
        assert s["routed"] == 1

    def test_stats_includes_buffer_when_set(self):
        buf = DirectBuffer(send_fn=lambda ch, data: None)
        mgr = _manager(buffer_strategy=buf)
        s = mgr.get_stats()
        assert "buffer" in s
        assert s["buffer"]["type"] == "direct"

    def test_stats_no_buffer_key_when_none(self):
        mgr = _manager()
        s = mgr.get_stats()
        assert "buffer" not in s
