# -*- coding: utf-8 -*-
"""Тесты Ф1 Task 1.7: команда router.relay (хаб-релей недоставляемых push'ей).

Дочерний процесс не может доставить push внешнему сокет-подписчику (канал
'backend_ctl' живёт только в router'е хаба) — RouterManager._relay_via_hub
однократно пересылает билет хабу командой router.relay. Здесь — обработчик:
регистрация (description для книжки 1.9, manages_own_reply) и пересылка билета
своим router'ом с гарантией метки _relayed (защита от циклов).
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands


class _FakeCommandManager:
    def __init__(self) -> None:
        self.handlers: dict = {}
        self.metadata: dict = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler
        self.metadata[name] = metadata or {}

    def dispatch(self, command: str, data: dict | None = None) -> dict:
        return self.handlers[command](data or {})


class _FakeRouter:
    def __init__(self) -> None:
        self.sent_async: list = []
        self.sent: list = []

    def send_async(self, message, priority="normal") -> None:
        self.sent_async.append((message, priority))

    def send(self, message) -> dict:
        self.sent.append(message)
        return {"status": "success"}


class _SyncOnlyRouter:
    """Router без send_async (минимальные/тестовые реализации IRouter)."""

    def __init__(self) -> None:
        self.sent: list = []

    def send(self, message) -> dict:
        self.sent.append(message)
        return {"status": "success"}


class _FakeServices:
    def __init__(self, router=None) -> None:
        self.command_manager = _FakeCommandManager()
        self.router_manager = router
        self.name = "ProcessManager"

    def _log_info(self, *a, **k) -> None: ...
    def _log_debug(self, *a, **k) -> None: ...


def _make(router=None):
    svc = _FakeServices(router=router)
    BuiltinCommands(svc)._register_relay_commands()
    return svc, svc.command_manager


class TestRegistration:
    def test_registered_with_description_and_own_reply(self) -> None:
        _svc, cm = _make(router=_FakeRouter())
        assert "router.relay" in cm.handlers
        meta = cm.metadata["router.relay"]
        assert meta.get("description"), "нет description (нужно для книжки 1.9)"
        # fire-and-forget: авто-reply инициатору не нужен (у relay нет request_id)
        assert meta.get("manages_own_reply") is True

    def test_skips_without_command_manager(self) -> None:
        svc = _FakeServices(router=_FakeRouter())
        svc.command_manager = None
        BuiltinCommands(svc)._register_relay_commands()  # не должно падать


class TestRelayHandler:
    def test_resends_ticket_via_own_router_async(self) -> None:
        router = _FakeRouter()
        _svc, cm = _make(router=router)
        ticket = {"type": "event", "command": "log.record", "targets": ["backend_ctl"], "_relayed": True}
        res = cm.dispatch("router.relay", {"ticket": ticket})
        assert res["success"] is True
        assert len(router.sent_async) == 1
        sent, _prio = router.sent_async[0]
        assert sent["command"] == "log.record"
        assert sent["_relayed"] is True

    def test_marks_relayed_if_sender_forgot(self) -> None:
        # Страховка от циклов: даже если отправитель не пометил билет.
        router = _FakeRouter()
        _svc, cm = _make(router=router)
        cm.dispatch("router.relay", {"ticket": {"type": "event", "targets": ["x"]}})
        sent, _ = router.sent_async[0]
        assert sent["_relayed"] is True

    def test_falls_back_to_sync_send(self) -> None:
        router = _SyncOnlyRouter()
        _svc, cm = _make(router=router)
        res = cm.dispatch("router.relay", {"ticket": {"type": "event", "targets": ["x"]}})
        assert res["success"] is True
        assert len(router.sent) == 1

    def test_rejects_ticket_without_targets(self) -> None:
        _svc, cm = _make(router=_FakeRouter())
        assert cm.dispatch("router.relay", {})["success"] is False
        assert cm.dispatch("router.relay", {"ticket": "not-a-dict"})["success"] is False
        assert cm.dispatch("router.relay", {"ticket": {"type": "event"}})["success"] is False

    def test_no_router_returns_error(self) -> None:
        _svc, cm = _make(router=None)
        res = cm.dispatch("router.relay", {"ticket": {"type": "event", "targets": ["x"]}})
        assert res["success"] is False
