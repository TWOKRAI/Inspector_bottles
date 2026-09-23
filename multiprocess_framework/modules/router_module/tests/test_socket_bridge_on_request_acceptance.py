# -*- coding: utf-8 -*-
"""Независимая приёмка колбэка ``on_request`` адаптера (Задача 4.4, RED).

Написано ДО реализации по дизайну лида. У ``SocketBridgeAdapter.__init__`` и
``setup_backend_ctl_channel`` ещё нет параметра ``on_request`` — конструктор
должен упасть ``TypeError`` на неожиданном keyword-аргументе.

Слепота: видел только публичный конструктор/``on_inbound`` в
``socket_bridge_adapter.py`` и сигнатуру ``setup_backend_ctl_channel`` в
``backend_ctl_endpoint.py``, не видел реализацию точечных намерений.
"""

from __future__ import annotations

from multiprocess_framework.modules.router_module.adapters.socket_bridge_adapter import (
    SocketBridgeAdapter,
)


class _FakeRouter:
    """Фейк RouterManager: request() отдаёт заданный результат, send() копит ответы."""

    def __init__(self, result):
        self._result = result
        self.requests = []
        self.sent = []

    def request(self, msg, timeout=None):
        self.requests.append((dict(msg), timeout))
        return self._result

    def send(self, response):
        self.sent.append(response)


def test_on_request_called_after_request_without_session_key():
    """on_request(msg, sid, result) зовётся ПОСЛЕ router.request, msg без ключа 'session'."""
    router = _FakeRouter(result={"success": True, "data": 123})
    calls = []

    def on_request(msg, sid, result):
        calls.append((dict(msg), sid, result))

    adapter = SocketBridgeAdapter(router, "backend_ctl", on_request=on_request)

    adapter.on_inbound({"command": "ping", "session": "sess-1", "request_id": "r1"})

    assert len(calls) == 1
    msg_seen, sid_seen, result_seen = calls[0]
    assert "session" not in msg_seen
    assert sid_seen == "sess-1"
    assert result_seen == {"success": True, "data": 123}
    # Ответ driver'у по-прежнему уходит — колбэк наблюдателя не подменяет доставку.
    assert len(router.sent) == 1


def test_on_request_exception_counted_and_response_still_sent():
    """Исключение внутри on_request гасится, считается в get_stats()['observer_errors'], ответ уходит."""
    router = _FakeRouter(result={"success": True})

    def on_request(msg, sid, result):
        raise RuntimeError("наблюдатель упал")

    adapter = SocketBridgeAdapter(router, "backend_ctl", on_request=on_request)

    adapter.on_inbound({"command": "ping", "session": "sess-2", "request_id": "r2"})

    assert len(router.sent) == 1
    stats = adapter.get_stats()
    assert stats["observer_errors"] == 1
