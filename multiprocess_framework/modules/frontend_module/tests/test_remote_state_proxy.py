# -*- coding: utf-8 -*-
"""Независимая приёмка ``RemoteStateProxy`` (Task 1.2, gui-service, RED).

Написано ДО реализации по ``remote_state_proxy.py`` (стадия INTERFACE, тела
``raise NotImplementedError``) и ``socket_client.py`` (тот же статус). Слепота:
видел эти два файла + ``state_store_module/proxy/state_proxy.py`` (базовый класс,
УЖЕ реализован — ``subscribe``/``on_state_changed``) + ``core/delta.py`` (``Delta``,
реализован) + существующие тесты ``router_module``. НЕ видел ``_impl/``, не
заглядывал в ``docs/reviews/2026-09-24_task-1.2-design.md``.

Упрощение, сделанное осознанно (не угадывание): «host set("a.b", 1)» из DESIGN
здесь смоделирован как ПРЯМАЯ рассылка настоящего ``Delta(...).to_dict()`` через
сокет хоста, а не как вызов настоящего ``StateStoreManager``. Механизм, который
проверяют эти тесты, — путь клиента push → cache/callback (``on_state_changed``,
``RemoteStateProxy`` поверх него), а не работоспособность серверного стора
(``docstring`` ``remote_state_proxy.py`` сам говорит: «хост не правится, обработчики
state.* уже есть» — то есть это существующий, отдельно проверенный код). Полная
проводка через реальный ``StateStoreManager`` — за пределами RED-бюджета этой
задачи и вносила бы вторую переменную (правильность серверного стора) в тест,
целящийся в клиентский транспорт.

``subscribe(..., sync=False)`` выбран намеренно вместо дефолтного ``sync=True``:
``sync=True`` ждал бы от хоста ответ на ``state.subscribe`` с точной формой,
которую интерфейс НЕ специфицирует (я бы её угадывал). ``sync=False`` —
fire-and-forget, не блокирует и не зависит от угаданной формы ответа; сама
проверка (push → callback) от этого выбора не страдает — предмет теста именно она.
"""

from __future__ import annotations

import threading
import time
from queue import Queue
from types import SimpleNamespace
from typing import Any, Callable, Dict
from unittest.mock import Mock

from multiprocess_framework.modules.frontend_module.bridge.remote_state_proxy import (
    RemoteStateProxy,
)
from multiprocess_framework.modules.router_module.adapters.socket_bridge_adapter import (
    SocketBridgeAdapter,
)
from multiprocess_framework.modules.router_module.channels.queue_channel import QueueChannel
from multiprocess_framework.modules.router_module.channels.socket_channel import SocketChannel
from multiprocess_framework.modules.router_module.channels.socket_client import SocketClient
from multiprocess_framework.modules.router_module.core.router_manager import RouterManager
from multiprocess_framework.modules.state_store_module.core.delta import Delta


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
        self._sock_ch.send(msg)

    def close(self) -> None:
        try:
            self.router.shutdown()
        finally:
            self._sock_ch.close()


def _make_command_host(commands: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]) -> _Host:
    """Реальный RouterManager + реальный SocketChannel(port=0), команды хоста — dict.

    Та же идиома (Mock command_manager), что в ``router_module/tests/test_router_manager.py``
    и продублирована в двух соседних файлах этого задания (нет общего conftest в FILES).
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


def _wait(predicate: Callable[[], bool], timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


# --------------------------------------------------------------------------- тесты


def test_subscribe_receives_delta_list() -> None:
    """AC4: subscribe('a.*', cb); host push state.changed(a.b=1) → cb([Delta]) за <1с."""
    host = _make_command_host({})
    try:
        client = SocketClient(host.host, host.port, sender="gui")
        client.connect()
        client.request({"type": "command", "command": "ping", "sender": "gui"}, timeout=2.0)  # хост принял сокет
        proxy = RemoteStateProxy(client, dispatch=lambda fn: fn())
        received: list = []
        proxy.subscribe("a.*", received.append, sync=False)

        delta = Delta("a.b", old_value=None, new_value=1, source="host").to_dict()
        t0 = time.monotonic()
        host.push({"type": "event", "command": "state.changed", "data": {"deltas": [delta]}})

        assert _wait(lambda: len(received) == 1, timeout=1.0), "дельта не дошла за 1с"
        assert time.monotonic() - t0 < 1.0
        assert received[0][0].path == "a.b"
        assert received[0][0].new_value == 1
    finally:
        host.close()


def test_subscription_survives_reconnect() -> None:
    """Hazard: close → connect → on_reconnected → новая дельта всё ещё доходит до cb.

    (Шаг refresh_fence из протокола реконнекта — метод RemoteCommandSender, не
    участвует в этом тесте: он не создаётся, проверяется только RemoteStateProxy.)
    """
    host = _make_command_host({})
    try:
        client = SocketClient(host.host, host.port, sender="gui")
        client.connect()
        proxy = RemoteStateProxy(client, dispatch=lambda fn: fn())
        received: list = []
        proxy.subscribe("a.*", received.append, sync=False)

        client.close()
        client.connect()
        client.request({"type": "command", "command": "ping", "sender": "gui"}, timeout=2.0)  # хост принял сокет
        proxy.on_reconnected()

        delta = Delta("a.c", old_value=None, new_value=2, source="host").to_dict()
        host.push({"type": "event", "command": "state.changed", "data": {"deltas": [delta]}})

        assert _wait(lambda: len(received) == 1, timeout=1.0), "дельта после реконнекта не дошла"
        assert received[0][0].path == "a.c"
    finally:
        host.close()


def test_callback_runs_via_dispatcher_not_reader_thread() -> None:
    """S2: колбэк подписчика исполняется через dispatch(fn), НИКОГДА не на reader-потоке.

    dispatch — «очередь, вычитываемая тестовым потоком» (DESIGN): сам dispatch(fn)
    зовётся на reader-потоке (доказывает, что доставка идёт инлайн там), а
    фактический вызов fn() тест делает сам, из главного потока — колбэк подписчика
    в принципе не может увидеть имя reader-потока.
    """
    host = _make_command_host({})
    try:
        client = SocketClient(host.host, host.port, sender="gui")
        client.connect()
        client.request({"type": "command", "command": "ping", "sender": "gui"}, timeout=2.0)  # хост принял сокет

        jobs: Queue = Queue()
        dispatch_threads: list = []

        def dispatch(fn: Callable[[], None]) -> None:
            dispatch_threads.append(threading.current_thread().name)
            jobs.put(fn)

        proxy = RemoteStateProxy(client, dispatch=dispatch)
        callback_threads: list = []
        proxy.subscribe("a.*", lambda deltas: callback_threads.append(threading.current_thread().name), sync=False)

        delta = Delta("a.b", old_value=None, new_value=1, source="host").to_dict()
        host.push({"type": "event", "command": "state.changed", "data": {"deltas": [delta]}})

        fn = jobs.get(timeout=2.0)
        assert dispatch_threads and dispatch_threads[0] == client._reader_thread_name, (
            "dispatch(fn) не позвали на reader-потоке — доставка не инлайн"
        )

        fn()  # тестовый (главный) поток — сознательно НЕ reader
        assert callback_threads == [threading.current_thread().name]
        assert callback_threads[0] != client._reader_thread_name
    finally:
        host.close()
