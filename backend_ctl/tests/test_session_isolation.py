# -*- coding: utf-8 -*-
"""Acceptance D.1a: два driver'а на одном порту изолированы (Вариант A, флаг ON).

Ядро acceptance родителя: два клиента НЕ видят reply/push друг друга. Поднимаем
реальный ``SocketChannel(session_isolation=True)`` + ``SocketBridgeAdapter(
session_isolation=True)`` + echo-router + ДВА подключённых ``BackendDriver``.
Проверяем изоляцию reply- и push-плоскостей через событийные очереди driver'ов,
плюс per-session subscriber (чинит коллизию общего "backend_ctl").

Не live: без ProcessManager/queue_registry — контур транспорта самодостаточен
(driver → SocketChannel → bridge → echo-router → адресный ответ/пуш обратно).
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

import pytest

from backend_ctl.driver import BackendDriver
from multiprocess_framework.modules.router_module.adapters.socket_bridge_adapter import (
    SocketBridgeAdapter,
)
from multiprocess_framework.modules.router_module.channels.socket_channel import SocketChannel


class _EchoRouter:
    """Фейк-router: request() эхо-резолвит команду, send() маршрутит по channel=."""

    def __init__(self, channel: SocketChannel) -> None:
        self._channel = channel
        self.calls: List[Dict[str, Any]] = []

    def request(self, message: Dict[str, Any], timeout: float = 5.0) -> Dict[str, Any]:
        self.calls.append(message)
        return {"success": True, "result": {"cmd": message.get("command")}}

    def send(self, message: Dict[str, Any]) -> Dict[str, Any]:
        if message.get("channel") == self._channel.name:
            return self._channel.send(message)
        return {"status": "error", "reason": "unknown channel"}


def _wait(pred, timeout: float = 2.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def two_drivers():
    channel = SocketChannel("backend_ctl", host="127.0.0.1", port=0, session_isolation=True)
    router = _EchoRouter(channel)
    adapter = SocketBridgeAdapter(router, "backend_ctl", session_isolation=True)
    channel._on_inbound = adapter.on_inbound
    assert channel.start()

    a = BackendDriver(host="127.0.0.1", port=channel.port)
    b = BackendDriver(host="127.0.0.1", port=channel.port)
    a.connect()
    b.connect()
    assert _wait(lambda: channel.get_info()["clients"] >= 2)
    # Первичная команда каждого driver'а биндит его session→сокет на канале.
    assert a.send_command("pA", "introspect.status", timeout=3.0)["success"] is True
    assert b.send_command("pB", "introspect.status", timeout=3.0)["success"] is True
    assert _wait(lambda: channel.get_info()["sessions"] >= 2)
    try:
        yield a, b, channel
    finally:
        a.close()
        b.close()
        channel.close()


class TestTwoClientIsolation:
    def test_distinct_session_scoped_subscribers(self, two_drivers) -> None:
        # log_untail/tail per-session: разные driver'ы = разные подписчики (раньше оба
        # тейлили под общим "backend_ctl", untail одного снёс бы хвост обоих).
        a, b, _ = two_drivers
        assert a._subscriber != b._subscriber
        assert a._subscriber == f"backend_ctl.{a._session}"
        assert b._subscriber == f"backend_ctl.{b._session}"

    def test_reply_not_leaked_to_other_client(self, two_drivers) -> None:
        a, b, _ = two_drivers
        b.events()  # drain на всякий случай
        res = a.send_command("pA", "introspect.handlers", timeout=3.0)
        assert res["success"] is True  # A получил СВОЙ ответ
        # B не должен увидеть reply A даже как чужое событие (изоляция reply-плоскости).
        time.sleep(0.15)
        assert b.events() == []

    def test_push_addressed_only_to_target_client(self, two_drivers) -> None:
        a, b, channel = two_drivers
        got_a: List[Dict[str, Any]] = []
        got_b: List[Dict[str, Any]] = []
        a.subscribe(got_a.append)
        b.subscribe(got_b.append)
        # Симулируем router-addressed push (мост Ф1.1b кладёт _address=[name, sid]).
        channel.send(
            {
                "type": "event",
                "command": "state.changed",
                "_address": ["backend_ctl", a._session],
                "data": {"deltas": [{"path": "processes.p.fps", "value": 30}]},
            }
        )
        assert _wait(lambda: len(got_a) >= 1)
        assert got_a[0]["data"]["deltas"][0]["value"] == 30
        time.sleep(0.15)
        assert got_b == []  # чужой push НЕ протёк к B

    def test_push_to_ghost_session_reaches_nobody(self, two_drivers) -> None:
        a, b, channel = two_drivers
        got_a: List[Dict[str, Any]] = []
        got_b: List[Dict[str, Any]] = []
        a.subscribe(got_a.append)
        b.subscribe(got_b.append)
        res = channel.send(
            {"type": "event", "command": "state.changed", "_address": ["backend_ctl", "ghost"], "data": {}}
        )
        assert res["status"] == "error"  # неизвестная сессия → error, не broadcast
        time.sleep(0.15)
        assert got_a == [] and got_b == []
