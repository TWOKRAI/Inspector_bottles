# -*- coding: utf-8 -*-
"""Тесты BackendDriver.

Юнит:
- request-id matching: ответ по id будит ожидающего;
- таймаут при отсутствии ответа;
- обёртки строят корректные router-сообщения (через билдеры).

Integration (loopback TCP):
- driver → SocketChannel → bridge-adapter → фейковый echo-router → ответ driver'у
  по request_id (полный round-trip без queue_registry).
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


# --- Юнит: request/timeout без реального сокета ---


class TestRequestMatching:
    def test_not_connected_returns_error(self) -> None:
        d = BackendDriver()
        res = d.send_command("preprocessor", "introspect.handlers")
        assert res["success"] is False
        assert "not connected" in res["error"]


# --- Integration: реальный loopback round-trip ---


class EchoRouter:
    """Фейковый router: request() резолвит «внутри системы» и возвращает result;
    send() с channel= кладёт ответ обратно в SocketChannel (как настоящий resolve)."""

    def __init__(self, channel: SocketChannel, handler) -> None:
        self._channel = channel
        self._handler = handler  # (msg) -> result dict

    def request(self, message: Dict[str, Any], timeout: float = 5.0) -> Dict[str, Any]:
        # Имитируем доставку в процесс и его ответ.
        return self._handler(message)

    def send(self, message: Dict[str, Any]) -> Dict[str, Any]:
        # channel=-маршрутизация → SocketChannel.send (как _resolve_channels у router).
        if message.get("channel") == self._channel.name:
            return self._channel.send(message)
        return {"status": "error", "reason": "unknown channel"}


@pytest.fixture
def loopback():
    """Поднять SocketChannel + bridge + echo-router; вернуть (driver, calls)."""
    calls: List[Dict[str, Any]] = []

    def handler(msg: Dict[str, Any]) -> Dict[str, Any]:
        calls.append(msg)
        target = (msg.get("targets") or ["?"])[0]
        return {"success": True, "result": {"target": target, "command": msg.get("command")}}

    channel = SocketChannel("backend_ctl", host="127.0.0.1", port=0)
    router = EchoRouter(channel, handler)
    adapter = SocketBridgeAdapter(router, "backend_ctl")
    channel._on_inbound = adapter.on_inbound  # привязать обработчик
    assert channel.start()

    driver = BackendDriver(host="127.0.0.1", port=channel.port)
    driver.connect()
    # дождаться регистрации клиента
    deadline = time.time() + 2.0
    while channel.get_info()["clients"] < 1 and time.time() < deadline:
        time.sleep(0.01)

    yield driver, calls

    driver.close()
    channel.close()


class TestIntegration:
    def test_send_command_round_trip(self, loopback) -> None:
        driver, calls = loopback
        res = driver.send_command("preprocessor", "introspect.handlers", timeout=3.0)
        assert res["success"] is True
        assert res["result"] == {"target": "preprocessor", "command": "introspect.handlers"}
        # router получил GUI-форму сообщения + reply-поля
        assert len(calls) == 1
        sent = calls[0]
        assert sent["type"] == "command"
        assert sent["command"] == "introspect.handlers"
        assert sent["targets"] == ["preprocessor"]
        assert sent["sender"] == "backend_ctl"
        assert sent["reply_to"] == "ProcessManager"
        assert "request_id" in sent

    def test_introspect_handlers_wrapper(self, loopback) -> None:
        driver, calls = loopback
        res = driver.introspect_handlers("camera", timeout=3.0)
        assert res["result"]["target"] == "camera"

    def test_set_register_builds_register_update(self, loopback) -> None:
        driver, calls = loopback
        driver.set_register("preprocessor", "resize", "width", 640, timeout=3.0)
        sent = calls[0]
        assert sent["command"] == "register_update"
        assert sent["data"] == {"plugin_name": "resize", "field": "width", "value": 640}

    def test_system_command_wraps_process_command(self, loopback) -> None:
        driver, calls = loopback
        driver.system_command({"cmd": "process.start", "process_name": "camera"}, timeout=3.0)
        sent = calls[0]
        assert sent["command"] == "process.command"
        assert sent["targets"] == ["ProcessManager"]
        assert sent["data"] == {"cmd": "process.start", "process_name": "camera"}

    def test_distinct_request_ids_matched(self, loopback) -> None:
        """Два последовательных запроса матчатся по своим id (не путаются)."""
        driver, _ = loopback
        r1 = driver.send_command("p1", "introspect.status", timeout=3.0)
        r2 = driver.send_command("p2", "introspect.status", timeout=3.0)
        assert r1["result"]["target"] == "p1"
        assert r2["result"]["target"] == "p2"
