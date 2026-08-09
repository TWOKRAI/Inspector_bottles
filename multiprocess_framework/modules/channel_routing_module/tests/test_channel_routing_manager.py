# -*- coding: utf-8 -*-
"""
Тесты ChannelRoutingManager.

Проверяет: initialize/shutdown, register_channel, buffer integration, get_stats.

**Ф4.6 (2026-08-05): блок TestRouting удалён вместе с проверяемым API.**
``route`` / ``register_route`` / ``register_broadcast`` снесены из базы: во всём
репозитории их звали ТОЛЬКО эти тесты — продовой записи через них не проходило
ни одной. Тесты буфера ехали тем же мёртвым путём, поэтому переписаны на живой
шов «буфер ↔ ``flush()`` менеджера»: именно он остался в базе и именно им
пользуются все четыре наследника.
"""

import time
from typing import Any, Dict, List

from ..interfaces import IChannel
from ..core.channel_routing_manager import ChannelRoutingManager
from ..buffers.direct_buffer import DirectBuffer
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
# Tests: buffer integration
# ---------------------------------------------------------------------------


class TestBufferIntegration:
    """Шов «менеджер ↔ буфер»: постановка в очередь и сброс по flush()."""

    def test_direct_buffer_writes_immediately(self):
        written = []
        buf = DirectBuffer(send_fn=lambda ch, data: written.append((ch, data)))
        mgr = _manager(buffer_strategy=buf)
        mgr.register_channel(_MockChannel("ch"))

        buf.enqueue("ch", {"x": 1})

        assert written == [("ch", {"x": 1})]

    def test_manager_flush_reaches_the_buffer(self):
        """``flush()`` менеджера обязан дойти до буфера — иначе хвост теряется молча.

        Ф7.4: батчевого буфера больше нет (запись синхронна), но контракт базы
        остался — она обязана звать ``flush`` у ЛЮБОЙ стратегии. Сторожим его
        на буфере-шпионе: без него менеджер с медленным стоком терял бы хвост
        молча, и заметили бы это только на живом стенде.
        """
        calls = []

        class _SpyBuffer:
            def start(self):
                pass

            def stop(self):
                pass

            def enqueue(self, channel, data, priority=None):
                calls.append(("enqueue", channel))

            def flush(self, channel=None):
                calls.append(("flush", channel))

            @property
            def stats(self):
                return {}

        mgr = _manager(buffer_strategy=_SpyBuffer())
        mgr.register_channel(_MockChannel("ch"))

        mgr.flush()

        assert ("flush", None) in calls

    def test_async_sender_buffer_delivers(self):
        received = []
        buf = AsyncSenderBuffer(send_fn=lambda ch, data: received.append((ch, data)))
        mgr = _manager(buffer_strategy=buf)
        mgr.register_channel(_MockChannel("ch"))

        buf.enqueue("ch", {"n": 1})
        buf.enqueue("ch", {"n": 2})

        deadline = time.monotonic() + 2.0
        while len(received) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
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


# ---------------------------------------------------------------------------
# Tests: база не владеет диспетчером (Ф4.6)
# ---------------------------------------------------------------------------


class TestBaseOwnsNoDispatcher:
    """Страж против воскрешения key-based диспетчера в базе.

    Слот жил в ``ChannelRoutingManager`` и доставался всем четырём наследникам.
    Пользовался им ровно один — ``RouterManager``, и то через алиас
    ``self.channel_dispatcher = self._dispatcher``; остальным трём он приезжал
    мёртвым, но выглядел общим механизмом. Ф4 вводит цепочку процессоров, и
    второй, никем не используемый механизм маршрутизации рядом с ней —
    приглашение перепутать их.

    Проверяется ОТСУТСТВИЕ, а не поведение: у отсутствия нет своего вызова,
    поэтому иначе оно не стережётся ничем и вернётся первым же рефакторингом.
    """

    def test_manager_has_no_dispatcher_slot(self):
        assert not hasattr(_manager(), "_dispatcher"), (
            "в базе снова появился key-based диспетчер — у Ф4 должен остаться один механизм"
        )

    def test_key_based_routing_api_is_gone(self):
        mgr = _manager()
        for name in ("route", "register_route", "register_broadcast"):
            assert not hasattr(mgr, name), f"метод {name}() вернулся в базу"

    def test_router_owns_its_own_dispatcher(self):
        """У роутера диспетчер СВОЙ — и он не приезжает из базы.

        Ровно этот шов сломался при сносе: снятие слота из базы обнулило
        живой ``channel_dispatcher`` роутера, потому что тот был его алиасом.
        """
        from ...router_module.core.router_manager import RouterManager

        router = RouterManager(manager_name="GuardRouter")
        assert router.channel_dispatcher is not None, "живой диспетчер роутера пропал"
        assert not hasattr(router, "_dispatcher"), "роутер снова получает диспетчер из базы, а не создаёт свой"
