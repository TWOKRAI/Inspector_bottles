# -*- coding: utf-8 -*-
"""Тесты SocketBridgeAdapter (мок-router).

Покрываем:
- on_inbound зовёт router.request с тем же msg и таймаутом из сообщения/дефолтом;
- ответ уходит через router.send с channel=<name>, request_id и result;
- ошибка request() → error-ответ, read-loop не падает (исключение не пробрасывается);
- ошибка send() проглатывается (best-effort).
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..adapters.socket_bridge_adapter import SocketBridgeAdapter


class FakeRouter:
    """Мок RouterManager: пишет вызовы, отдаёт сконфигурированный результат."""

    def __init__(self, request_result: Any = None, request_raises: bool = False, send_raises: bool = False) -> None:
        self.request_calls: List[Dict[str, Any]] = []
        self.request_kwargs: List[Dict[str, Any]] = []
        self.sent: List[Dict[str, Any]] = []
        self._request_result = request_result if request_result is not None else {"success": True}
        self._request_raises = request_raises
        self._send_raises = send_raises

    def request(self, message: Dict[str, Any], timeout: float = 5.0) -> Dict[str, Any]:
        self.request_calls.append(message)
        self.request_kwargs.append({"timeout": timeout})
        if self._request_raises:
            raise RuntimeError("boom")
        return self._request_result

    def send(self, message: Dict[str, Any]) -> Dict[str, Any]:
        if self._send_raises:
            raise RuntimeError("send failed")
        self.sent.append(message)
        return {"status": "success"}


def _msg(**extra: Any) -> Dict[str, Any]:
    base = {
        "type": "command",
        "command": "introspect.handlers",
        "data_type": "introspect.handlers",
        "sender": "backend_ctl",
        "targets": ["preprocessor"],
        "data": {},
        "request_id": "corr-1",
        "reply_to": "ProcessManager",
    }
    base.update(extra)
    return base


class TestHappyPath:
    def test_request_called_with_same_msg(self) -> None:
        router = FakeRouter(request_result={"success": True, "result": {"k": 1}})
        adapter = SocketBridgeAdapter(router, "backend_ctl")
        m = _msg()
        adapter.on_inbound(m)
        assert router.request_calls == [m]

    def test_default_timeout_used(self) -> None:
        router = FakeRouter()
        adapter = SocketBridgeAdapter(router, "backend_ctl", default_timeout=3.0)
        adapter.on_inbound(_msg())
        assert router.request_kwargs[0]["timeout"] == 3.0

    def test_timeout_from_message_overrides(self) -> None:
        router = FakeRouter()
        adapter = SocketBridgeAdapter(router, "backend_ctl", default_timeout=5.0)
        adapter.on_inbound(_msg(timeout=1.5))
        assert router.request_kwargs[0]["timeout"] == 1.5

    def test_response_shape(self) -> None:
        router = FakeRouter(request_result={"success": True, "result": {"ok": 1}})
        adapter = SocketBridgeAdapter(router, "backend_ctl")
        adapter.on_inbound(_msg())
        assert len(router.sent) == 1
        resp = router.sent[0]
        assert resp["type"] == "response"
        assert resp["channel"] == "backend_ctl"
        assert resp["request_id"] == "corr-1"
        assert resp["result"] == {"success": True, "result": {"ok": 1}}


class TestVersionSkewTolerance:
    """Пин ДО session-isolation (D.1, §10): неизвестное top-level поле в команде
    не ломает обработку. Новее-сервера driver кладёт поля, которых сервер не знает
    (напр. будущий `session`) — request() обязан отработать штатно, не упасть.
    После ввода изоляции адаптер `pop`'нет ТОЛЬКО `session`; любое иное лишнее
    поле по-прежнему доезжает до request — этот пин это и стережёт.
    """

    def test_unknown_top_level_field_passes_through_to_request(self) -> None:
        router = FakeRouter(request_result={"success": True})
        adapter = SocketBridgeAdapter(router, "backend_ctl")
        m = _msg(future_field="skew")
        adapter.on_inbound(m)
        assert router.request_calls[0].get("future_field") == "skew"
        resp = router.sent[0]
        assert resp["type"] == "response"
        assert resp["result"] == {"success": True}


class TestSessionIsolation:
    """D.1: поле `session` снимается из msg ВСЕГДА (защита внутренней маршрутизации
    от просачивания), а обратный адрес возвращается в response ТОЛЬКО при isolation ON.
    """

    def test_session_popped_before_request_and_no_echo_when_off(self) -> None:
        router = FakeRouter(request_result={"success": True})
        adapter = SocketBridgeAdapter(router, "backend_ctl")  # isolation off (default)
        adapter.on_inbound(_msg(session="sid-x"))
        assert "session" not in router.request_calls[0]  # не течёт во внутренний handler
        assert "session" not in router.sent[0]  # и не возвращается в response при OFF

    def test_session_popped_but_echoed_in_response_when_on(self) -> None:
        router = FakeRouter(request_result={"success": True})
        adapter = SocketBridgeAdapter(router, "backend_ctl", session_isolation=True)
        adapter.on_inbound(_msg(session="sid-x"))
        assert "session" not in router.request_calls[0]  # всё равно снят до request
        assert router.sent[0]["session"] == "sid-x"  # но возвращён как обратный адрес

    def test_no_session_field_no_echo_when_on(self) -> None:
        router = FakeRouter(request_result={"success": True})
        adapter = SocketBridgeAdapter(router, "backend_ctl", session_isolation=True)
        adapter.on_inbound(_msg())  # без session
        assert "session" not in router.sent[0]


class TestErrorHandling:
    def test_request_error_becomes_error_response(self) -> None:
        router = FakeRouter(request_raises=True)
        adapter = SocketBridgeAdapter(router, "backend_ctl")
        adapter.on_inbound(_msg())  # не должно бросить
        resp = router.sent[0]
        assert resp["result"]["success"] is False
        assert "boom" in resp["result"]["error"]

    def test_send_error_swallowed(self) -> None:
        router = FakeRouter(send_raises=True)
        adapter = SocketBridgeAdapter(router, "backend_ctl")
        # send падает, но on_inbound не пробрасывает (read-loop жив)
        adapter.on_inbound(_msg())

    def test_send_error_counted_not_silent_a4(self) -> None:
        """A-4 (bug-hunt 2026-07-20 §5): потеря ответа driver'у больше не проходит
        безмолвно — счётчик lost_responses растёт на каждый провал send(), виден
        через get_stats(). Раньше здесь было голое `except Exception: pass`."""
        router = FakeRouter(send_raises=True)
        adapter = SocketBridgeAdapter(router, "backend_ctl")
        assert adapter.get_stats() == {"lost_responses": 0}

        adapter.on_inbound(_msg())
        assert adapter.get_stats() == {"lost_responses": 1}

        adapter.on_inbound(_msg())
        assert adapter.get_stats() == {"lost_responses": 2}

    def test_successful_send_does_not_increment_lost_responses(self) -> None:
        router = FakeRouter()  # send не падает
        adapter = SocketBridgeAdapter(router, "backend_ctl")
        adapter.on_inbound(_msg())
        assert adapter.get_stats() == {"lost_responses": 0}

    def test_missing_request_id_passes_none(self) -> None:
        router = FakeRouter()
        adapter = SocketBridgeAdapter(router, "backend_ctl")
        m = _msg()
        del m["request_id"]
        adapter.on_inbound(m)
        assert router.sent[0]["request_id"] is None
