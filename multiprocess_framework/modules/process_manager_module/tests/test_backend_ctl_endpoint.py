# -*- coding: utf-8 -*-
"""Тесты backend_ctl_endpoint — гейт + поднятие/остановка SocketChannel.

Покрываем:
- is_enabled: только BACKEND_CTL=1;
- setup: гейт закрыт → None, не трогает router;
- setup: гейт открыт → канал поднят, зарегистрирован в router, bind на свободный порт;
- setup: router=None → None (без падения);
- teardown: закрывает канал + unregister;
- end-to-end: driver подключается к поднятому endpoint и получает ответ через fake-router.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from ..process.backend_ctl_endpoint import (
    BACKEND_CTL_CHANNEL,
    is_enabled,
    setup_backend_ctl_channel,
    teardown_backend_ctl_channel,
)


class FakeRouter:
    """Мок router: реестр каналов + request()/send() как в SocketBridgeAdapter-тестах."""

    def __init__(self, handler=None) -> None:
        self.channels: Dict[str, Any] = {}
        self._handler = handler or (lambda msg: {"success": True, "result": {"echo": msg.get("command")}})

    def register_channel(self, channel: Any) -> bool:
        self.channels[channel.name] = channel
        return True

    def unregister_channel(self, name: str) -> bool:
        return self.channels.pop(name, None) is not None

    def request(self, message: Dict[str, Any], timeout: float = 5.0) -> Dict[str, Any]:
        return self._handler(message)

    def send(self, message: Dict[str, Any]) -> Dict[str, Any]:
        ch = self.channels.get(message.get("channel"))
        if ch is not None:
            return ch.send(message)
        return {"status": "error", "reason": "no channel"}


class TestGate:
    def test_is_enabled_only_for_1(self) -> None:
        assert is_enabled({"BACKEND_CTL": "1"}) is True
        assert is_enabled({"BACKEND_CTL": "0"}) is False
        assert is_enabled({"BACKEND_CTL": "true"}) is False
        assert is_enabled({}) is False

    def test_setup_gate_closed_returns_none(self) -> None:
        router = FakeRouter()
        ch = setup_backend_ctl_channel(router, env={})
        assert ch is None
        assert router.channels == {}

    def test_setup_router_none_returns_none(self) -> None:
        ch = setup_backend_ctl_channel(None, env={"BACKEND_CTL": "1"})
        assert ch is None


class TestSetupTeardown:
    def test_setup_gate_open_registers_channel(self) -> None:
        router = FakeRouter()
        ch = setup_backend_ctl_channel(router, host="127.0.0.1", port=0, env={"BACKEND_CTL": "1"})
        try:
            assert ch is not None
            assert ch.name == BACKEND_CTL_CHANNEL
            assert BACKEND_CTL_CHANNEL in router.channels
            assert ch.port > 0
            assert ch.get_info()["bound"] is True
        finally:
            teardown_backend_ctl_channel(ch, router)

    def test_teardown_closes_and_unregisters(self) -> None:
        router = FakeRouter()
        ch = setup_backend_ctl_channel(router, port=0, env={"BACKEND_CTL": "1"})
        teardown_backend_ctl_channel(ch, router)
        assert BACKEND_CTL_CHANNEL not in router.channels
        assert ch.get_info()["bound"] is False

    def test_teardown_none_safe(self) -> None:
        teardown_backend_ctl_channel(None)  # не падает


class TestEndToEnd:
    def test_driver_round_trip_through_endpoint(self) -> None:
        from backend_ctl.driver import BackendDriver

        calls: List[Dict[str, Any]] = []

        def handler(msg: Dict[str, Any]) -> Dict[str, Any]:
            calls.append(msg)
            return {"success": True, "result": {"target": (msg.get("targets") or ["?"])[0]}}

        router = FakeRouter(handler=handler)
        ch = setup_backend_ctl_channel(router, port=0, env={"BACKEND_CTL": "1"})
        assert ch is not None
        driver = BackendDriver(host="127.0.0.1", port=ch.port)
        try:
            driver.connect()
            deadline = time.time() + 2.0
            while ch.get_info()["clients"] < 1 and time.time() < deadline:
                time.sleep(0.01)
            res = driver.introspect_handlers("preprocessor", timeout=3.0)
            assert res["success"] is True
            assert res["result"]["target"] == "preprocessor"
            assert calls[0]["command"] == "introspect.handlers"
        finally:
            driver.close()
            teardown_backend_ctl_channel(ch, router)
