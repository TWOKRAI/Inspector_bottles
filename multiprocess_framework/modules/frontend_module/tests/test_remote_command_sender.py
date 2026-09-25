# -*- coding: utf-8 -*-
"""Независимая приёмка ``RemoteCommandSender`` (Task 1.2, gui-service, RED).

Написано ДО реализации по ``remote_command_sender.py`` (стадия INTERFACE, тела
``raise NotImplementedError``) и ``socket_client.py`` (тот же статус). Слепота:
видел эти два файла + ``command_sender.py`` (базовый класс, УЖЕ реализован) +
``message_module/fencing/token.py`` (``make_fence_stamp_middleware`` — существующая,
реализованная фабрика) + существующие тесты ``router_module``. НЕ видел ``_impl/``,
не заглядывал в ``docs/reviews/2026-09-24_task-1.2-design.md``.

Хост — тот же харнесс, что в ``router_module/tests/test_socket_client.py``
(намеренно продублирован, а не импортирован оттуда: FILES этого задания не
включают общий conftest/helpers-модуль, а копия ~60 строк дешевле, чем внецелевой
файл).
"""

from __future__ import annotations

import threading
import time
from queue import Queue
from types import SimpleNamespace
from typing import Any, Callable, Dict
from unittest.mock import Mock

from multiprocess_framework.modules.frontend_module.bridge.remote_command_sender import (
    RemoteCommandSender,
)
from multiprocess_framework.modules.message_module.fencing.token import (
    make_fence_stamp_middleware,
)
from multiprocess_framework.modules.router_module.adapters.socket_bridge_adapter import (
    SocketBridgeAdapter,
)
from multiprocess_framework.modules.router_module.channels.queue_channel import QueueChannel
from multiprocess_framework.modules.router_module.channels.socket_channel import SocketChannel
from multiprocess_framework.modules.router_module.channels.socket_client import SocketClient
from multiprocess_framework.modules.router_module.core.router_manager import RouterManager


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

    def close(self) -> None:
        try:
            self.router.shutdown()
        finally:
            self._sock_ch.close()


def _make_command_host(commands: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]) -> _Host:
    """Реальный RouterManager + реальный SocketChannel(port=0), команды хоста — dict.

    «Процесс-заглушка, регистрирующая свою команду» — Mock command_manager,
    идиома из ``router_module/tests/test_router_manager.py::TestDispatchCommand``.
    """
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
    box: Dict[str, Any] = {}

    def _run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["exc"] = exc

    t = threading.Thread(target=_run, daemon=True, name="test-caller")
    t.start()
    t.join(timeout)
    assert not t.is_alive(), f"вызов не завершился за {timeout}с — зависание вместо ошибки"
    if "exc" in box:
        raise box["exc"]
    return box.get("result")


def _capture(sink: list) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    def _mw(msg: Dict[str, Any]) -> Dict[str, Any]:
        sink.append(dict(msg))
        return msg

    return _mw


# --------------------------------------------------------------------------- тесты


def test_ping_request_command_envelope() -> None:
    """AC2: request_command('ping') → {success: True, result: ...} за <1с."""
    host = _make_command_host({"ping": lambda msg: {"pong": True}})
    try:
        client = SocketClient(host.host, host.port, sender="gui")
        client.connect()
        sender = RemoteCommandSender(client, name="gui")

        t0 = time.monotonic()
        resp = _call_with_deadline(lambda: sender.request_command("host", "ping", {}), timeout=5.0)
        elapsed = time.monotonic() - t0

        assert elapsed < 1.0, f"roundtrip {elapsed:.3f}с — дольше секунды"
        assert resp["success"] is True
        assert resp["result"] == {"pong": True}
    finally:
        host.close()


def test_fence_stamp_structure_matches_builtin_gui() -> None:
    """AC3: _fence на проводе — РОВНО {sender, inc, epoch}, как у make_fence_stamp_middleware.

    Обходит спорный случай "host не знает имя клиента" (DESIGN: "штамп должен
    присутствовать, inc тогда 0"; докстринг remote_command_sender.py: "фабрика
    НЕ штампует вовсе, fail-open" — прямое противоречие, см. отчёт тестера).
    Здесь fence задан ЯВНО конструктору ((3, 7)) — по интерфейсу это делает
    refresh_fence no-op и inc/epoch заведомо не None, так что спорная ветка не
    участвует в этой проверке; структуру ключей она пинит однозначно.
    """
    host = _make_command_host({"ping": lambda msg: {"pong": True}})
    try:
        client = SocketClient(host.host, host.port, sender="gui")
        client.connect()
        # fence-middleware регистрируется ВНУТРИ конструктора — сначала сендер,
        # потом наш перехватчик, иначе перехватчик увидит сообщение ДО штампа.
        sender = RemoteCommandSender(client, name="gui", fence=lambda: (3, 7))
        captured: list = []
        client.add_send_middleware(_capture(captured))

        _call_with_deadline(lambda: sender.request_command("host", "ping", {}), timeout=5.0)

        assert captured, "исходящее не перехвачено"
        wire_fence = captured[-1].get("_fence")
        assert wire_fence is not None, "_fence отсутствует на проводе"

        reference = make_fence_stamp_middleware("gui", lambda: (3, 7))({"command": "noop"})
        assert set(wire_fence.keys()) == {"sender", "inc", "epoch"}
        assert set(wire_fence.keys()) == set(reference["_fence"].keys())
    finally:
        host.close()


def test_refresh_fence_after_reconnect_no_old_stamp() -> None:
    """Hazard (г) / F1: неудачный refresh_fence после реконнекта сбрасывает fence в
    (None, None) — старый штамп (inc=3, epoch=7) не переживает реконнект."""
    known = {"value": True}

    def _status(msg: Dict[str, Any]) -> Dict[str, Any]:
        if known["value"]:
            return {"epoch": 7, "processes": {"gui": {"incarnation": 3}}}
        return {"epoch": 9, "processes": {}}

    host = _make_command_host({"supervision.status": _status})
    try:
        client = SocketClient(host.host, host.port, sender="gui")
        client.connect()
        sender = RemoteCommandSender(client, name="gui")  # fence=None → (None, None) до refresh
        captured: list = []
        client.add_send_middleware(_capture(captured))

        _call_with_deadline(sender.refresh_fence, timeout=5.0)
        _call_with_deadline(lambda: client.send_nowait({"command": "noop"}), timeout=5.0)
        assert captured[-1].get("_fence") == {"sender": "gui", "inc": 3, "epoch": 7}, (
            "первый refresh_fence не поставил ожидаемый штамп — тест не может проверить, что он потом пропал"
        )

        known["value"] = False  # хост "забыл" клиента (топология сменилась)
        client.close()
        client.connect()
        _call_with_deadline(sender.refresh_fence, timeout=5.0)
        _call_with_deadline(lambda: client.send_nowait({"command": "noop"}), timeout=5.0)

        stamp_after = captured[-1].get("_fence")
        assert stamp_after != {"sender": "gui", "inc": 3, "epoch": 7}, (
            "старый штамп (inc=3, epoch=7) пережил неудачный refresh_fence — нарушение F1"
        )
    finally:
        host.close()


def test_two_senders_multiplex_by_request_id() -> None:
    """Edge case: два RemoteCommandSender на ОДНОМ client не путают ответы —
    мультиплексирование по request_id (I2 SocketClient), не по отправителю."""

    def _echo(msg: Dict[str, Any]) -> Dict[str, Any]:
        time.sleep(0.05)
        return {"tag": (msg.get("data") or {}).get("tag")}

    host = _make_command_host({"echo": _echo})
    try:
        client = SocketClient(host.host, host.port, sender="gui")
        client.connect()
        sender_a = RemoteCommandSender(client, name="gui")
        sender_b = RemoteCommandSender(client, name="gui")

        results: Dict[str, Any] = {}

        def _call(sender: RemoteCommandSender, tag: str) -> None:
            results[tag] = sender.request_command("host", "echo", {"tag": tag})

        ta = threading.Thread(target=_call, args=(sender_a, "A"), daemon=True, name="caller-A")
        tb = threading.Thread(target=_call, args=(sender_b, "B"), daemon=True, name="caller-B")
        ta.start()
        tb.start()
        ta.join(5.0)
        tb.join(5.0)
        assert not ta.is_alive() and not tb.is_alive(), "зависание — мультиплексирование не работает"

        assert results.get("A", {}).get("result") == {"tag": "A"}
        assert results.get("B", {}).get("result") == {"tag": "B"}
    finally:
        host.close()
