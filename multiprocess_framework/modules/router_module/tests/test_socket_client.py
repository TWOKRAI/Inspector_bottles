# -*- coding: utf-8 -*-
"""Независимая приёмка ``SocketClient`` (Task 1.2, gui-service, RED).

Написано ДО реализации по интерфейсу ``socket_client.py`` (стадия INTERFACE,
все тела ``raise NotImplementedError``). Слепота: видел только
``socket_client.py`` (докстринги/сигнатуры), ``socket_channel.py``,
``socket_bridge_adapter.py`` и существующие тесты этих файлов
(``test_socket_channel.py``, ``test_router_manager.py``,
``test_socket_bridge_on_request_acceptance.py``) — НЕ видел ``_impl/`` (если
он уже есть) и не заглядывал в диз-документ ``docs/reviews/2026-09-24_task-1.2-design.md``.

Хост в этих тестах — РЕАЛЬНЫЙ ``RouterManager`` + РЕАЛЬНЫЙ ``SocketChannel(port=0)``
+ РЕАЛЬНЫЙ ``SocketBridgeAdapter``; «процесс-заглушка, регистрирующая свою команду
ping» реализован как ``Mock`` для ``command_manager`` — идиома ОДНА В ОДНУ
позаимствована из ``router_module/tests/test_router_manager.py::TestDispatchCommand``
(тот же приём: ``router.process = SimpleNamespace(command_manager=Mock(...))``),
это не изобретённый мной API, а существующий паттерн этого самого кодабейза.
"""

from __future__ import annotations

import threading
import time
from queue import Queue
from types import SimpleNamespace
from typing import Any, Callable, Dict
from unittest.mock import Mock

import pytest

from ..adapters.socket_bridge_adapter import SocketBridgeAdapter
from ..channels.queue_channel import QueueChannel
from ..channels.socket_channel import SocketChannel
from ..channels.socket_client import SocketClient, SocketConnectionLost
from ..core.router_manager import RouterManager


# --------------------------------------------------------------------------- харнесс
class _Host:
    def __init__(self, router: RouterManager, sock_ch: SocketChannel) -> None:
        self.router = router
        self._sock_ch = sock_ch

    @property
    def host(self) -> str:
        return "127.0.0.1"

    @property
    def port(self) -> int:
        return self._sock_ch.port

    def push(self, msg: Dict[str, Any]) -> None:
        """Прямая рассылка через сокет хоста (мимо request/response) — для push-тестов."""
        self._sock_ch.send(msg)

    def close(self) -> None:
        try:
            self.router.shutdown()
        finally:
            self._sock_ch.close()


def _make_command_host(commands: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]) -> _Host:
    """Реальный RouterManager + реальный SocketChannel(port=0), команды хоста — dict."""
    loop_q: Queue = Queue()
    router = RouterManager(manager_name="host")
    router.register_channel(QueueChannel("self", loop_q))

    def _get_command_info(name: str):
        return {"key": name, "metadata": {}} if name in commands else None

    def _handle_command(msg: Dict[str, Any]) -> Dict[str, Any]:
        handler = commands.get(msg.get("command"))
        if handler is None:
            return {"status": "error", "reason": "no handler"}
        return handler(msg)

    cm = Mock()
    cm.get_command_info = Mock(side_effect=_get_command_info)
    cm.handle_command = Mock(side_effect=_handle_command)
    router.process = SimpleNamespace(command_manager=cm)

    to_self = RouterManager._make_channel_handler("self")
    for key in list(commands) + ["command.response"]:
        router.register_channel_handler(key, to_self)

    router.initialize()
    router.start_listening(poll_interval=0.01)

    adapter = SocketBridgeAdapter(router, "backend_ctl")
    sock_ch = SocketChannel("backend_ctl", host="127.0.0.1", port=0, on_inbound=adapter.on_inbound)
    assert sock_ch.start() is True
    router.register_channel(sock_ch)

    return _Host(router, sock_ch)


def _call_with_deadline(fn: Callable[[], Any], timeout: float = 5.0) -> Any:
    """Выполнить fn() в daemon-потоке с join-дедлайном; исключение — пробросить сюда.

    Проектное правило: любой вызов, который может заблокироваться, должен идти в
    daemon-потоке с join-дедлайном — зависший тест хуже отсутствующего.
    """
    box: Dict[str, Any] = {}

    def _run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробрасываем в вызывающий поток ниже
            box["exc"] = exc

    t = threading.Thread(target=_run, daemon=True, name="test-caller")
    t.start()
    t.join(timeout)
    assert not t.is_alive(), f"вызов не завершился за {timeout}с — зависание вместо ошибки"
    if "exc" in box:
        raise box["exc"]
    return box.get("result")


def _wait(predicate: Callable[[], bool], timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


# --------------------------------------------------------------------------- тесты


def test_request_roundtrip_under_one_second() -> None:
    """AC2 (уровень транспорта): request() отвечает конвертом {success, result} за <1с."""
    host = _make_command_host({"ping": lambda msg: {"pong": True}})
    try:
        client = SocketClient(host.host, host.port, sender="gui")
        client.connect()
        t0 = time.monotonic()
        resp = _call_with_deadline(lambda: client.request({"command": "ping"}), timeout=5.0)
        elapsed = time.monotonic() - t0
        assert elapsed < 1.0, f"roundtrip {elapsed:.3f}с — дольше секунды"
        assert resp["success"] is True
        assert resp["result"] == {"pong": True}
    finally:
        host.close()


def test_drop_during_request_errors_within_timeout() -> None:
    """I4: разрыв соединения ВО ВРЕМЯ request() → _lost_exc за ≤ timeout, не зависание."""
    host = _make_command_host({"slow": lambda msg: {"ok": True}})
    try:
        client = SocketClient(host.host, host.port, sender="gui", default_timeout=5.0)
        client.connect()

        def _drop_soon() -> None:
            time.sleep(0.2)
            host.close()  # обрывает соединение со стороны хоста

        threading.Thread(target=_drop_soon, daemon=True, name="drop-host").start()

        with pytest.raises(SocketConnectionLost):
            _call_with_deadline(lambda: client.request({"command": "slow"}, timeout=3.0), timeout=5.0)
    finally:
        host.close()


def test_push_without_request_id_reaches_listener() -> None:
    """I2: сообщение без request_id, которого никто не ждёт, — push → add_push_listener."""
    host = _make_command_host({})
    try:
        received: list = []
        client = SocketClient(host.host, host.port, sender="gui")
        client.add_push_listener(received.append)
        client.connect()

        host.push({"command": "state.changed", "note": "без request_id — это push"})

        assert _wait(lambda: len(received) == 1, timeout=2.0), "push не дошёл за 2с"
        assert received[0]["command"] == "state.changed"
    finally:
        host.close()
