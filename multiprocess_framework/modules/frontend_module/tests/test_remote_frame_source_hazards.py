# -*- coding: utf-8 -*-
"""Hazard-тесты автора ``RemoteFrameSource`` (Task 1.3, gui-service).

Что может сломаться в ЭТОМ механизме, раз он так построен:

(a) Колбэк кадра исполняется ``dispatch``'ем. Если копия/колбэк уедут на reader-поток
    клиента, медленный колбэк заморозит ВСЁ, что клиент принимает: ответы на
    ``request`` других потребителей (``RemoteStateProxy``, ``RemoteCommandSender``)
    повиснут до таймаута. Проверка: колбэк заблокирован, и в это время ``request``
    на том же клиенте получает ответ.
(b) ``close()`` ждёт поток копирования. Колбэк, исполняемый прямо на нём
    (``dispatch=lambda fn: fn()``), может не вернуться никогда — ``close()`` обязан
    выйти по дедлайну, а не висеть вместе с ним.

Любой блокирующий вызов — в daemon-потоке с join-дедлайном.
"""

from __future__ import annotations

import threading
import time
import uuid
from multiprocessing import shared_memory
from queue import Queue
from types import SimpleNamespace
from typing import Any, Callable, Dict
from unittest.mock import Mock

import numpy as np

from multiprocess_framework.modules.frontend_module.bridge.remote_frame_source import RemoteFrameSource
from multiprocess_framework.modules.router_module.adapters.socket_bridge_adapter import SocketBridgeAdapter
from multiprocess_framework.modules.router_module.channels.queue_channel import QueueChannel
from multiprocess_framework.modules.router_module.channels.socket_channel import SocketChannel
from multiprocess_framework.modules.router_module.channels.socket_client import SocketClient
from multiprocess_framework.modules.router_module.core.router_manager import RouterManager
from multiprocess_framework.modules.shared_resources_module.memory.format.buffer import (
    calculate_buffer_size,
    pack_images,
)


def _make_host(commands: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]):
    """Реальный RouterManager + SocketChannel(port=0) — харнесс ``test_socket_client.py``."""
    loop_q: Queue = Queue()
    router = RouterManager(manager_name="host")
    router.register_channel(QueueChannel("self", loop_q))
    cm = Mock()
    cm.get_command_info = Mock(side_effect=lambda n: {"key": n, "metadata": {}} if n in commands else None)
    cm.handle_command = Mock(side_effect=lambda m: commands[m["command"]](m))
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
    return router, sock_ch


def _in_thread(fn: Callable[[], Any], deadline: float) -> Dict[str, Any]:
    box: Dict[str, Any] = {}

    def _run() -> None:
        t0 = time.monotonic()
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["exc"] = exc
        box["elapsed"] = time.monotonic() - t0

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(deadline)
    box["alive"] = t.is_alive()
    return box


def _segment() -> shared_memory.SharedMemory:
    frame = np.full((48, 64, 3), 9, dtype=np.uint8)
    size = calculate_buffer_size(1, frame.shape, frame.dtype, seqlock=False)
    shm = shared_memory.SharedMemory(name=f"t13h{uuid.uuid4().hex[:8]}", create=True, size=size)
    pack_images(shm.buf, [frame], frame.shape, frame.dtype, seqlock=False)
    return shm


def _push(sock_ch: SocketChannel, address: str, name: str, bseq: int) -> None:
    sock_ch.send(
        {
            "type": "event",
            "targets": [address],
            "command": "frames.frame",
            "sender": "gui",
            "data": {"sender": "camA", "name": name, "idx": 0, "seqlock": False, "bseq": bseq, "ts": time.time()},
        }
    )


class _Stand:
    """Хост + подключённый клиент + подписанный источник с блокирующимся колбэком."""

    def __init__(self) -> None:
        self.router, self.sock_ch = _make_host(
            {
                "frames.subscribe": lambda m: {"success": True, "seqlock": False, "owner_incarnation": False},
                "frames.unsubscribe": lambda m: {"success": True, "removed": True},
                "ping": lambda m: {"pong": True},
            }
        )
        self.shm = _segment()
        self.client = SocketClient("127.0.0.1", self.sock_ch.port, sender="backend_ctl")
        self.client.connect()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.source = RemoteFrameSource(self.client, dispatch=lambda fn: fn())

        def _blocking_cb(sender: str, frame: np.ndarray, bseq: int) -> None:
            self.entered.set()
            self.release.wait(10.0)

        sub = _in_thread(lambda: self.source.subscribe(None, _blocking_cb, timeout=3.0), deadline=4.0)
        assert not sub["alive"] and "exc" not in sub, sub

    def close(self) -> None:
        self.release.set()
        _in_thread(self.source.close, deadline=4.0)
        self.client.close()
        self.shm.close()
        self.shm.unlink()
        self.router.shutdown()
        self.sock_ch.close()


def test_a_blocked_callback_does_not_block_client_reader_thread() -> None:
    """(a) Колбэк висит → ответ на ``request`` того же клиента всё равно приходит < 1 с.

    Инъекция: копия+колбэк на reader-потоке (``_on_push`` зовёт ``_process`` сам) →
    reader занят колбэком, ``ping`` досиживает до таймаута → красный."""
    stand = _Stand()
    try:
        _push(stand.sock_ch, stand.client.subscriber_address, stand.shm.name, bseq=1)
        assert stand.entered.wait(3.0), "колбэк не вызван — сценарий не воспроизведён"

        box = _in_thread(lambda: stand.client.request({"type": "command", "command": "ping"}, timeout=2.0), 3.0)
        assert not box["alive"], "request повис"
        assert box.get("result", {}).get("success") is True, f"reader-поток клиента занят колбэком: {box}"
        assert box["elapsed"] < 1.0, f"ответ пришёл только через {box['elapsed']:.2f}с"
    finally:
        stand.close()


def test_b_close_during_in_flight_callback_returns_by_deadline() -> None:
    """(b) Колбэк висит на потоке копирования → ``close()`` возвращается за ≤ 2.5 с.

    Инъекция: ``thread.join()`` без таймаута в ``close`` → ``close`` висит до release (10 с)
    → join-дедлайн теста 4 с истекает → красный (а не зависший прогон)."""
    stand = _Stand()
    try:
        _push(stand.sock_ch, stand.client.subscriber_address, stand.shm.name, bseq=1)
        assert stand.entered.wait(3.0), "колбэк не вызван — сценарий не воспроизведён"

        box = _in_thread(stand.source.close, deadline=4.0)
        assert not box["alive"], "close() завис вместе с колбэком"
        assert "exc" not in box, f"close() бросил: {box['exc']!r}"
        assert box["elapsed"] < 2.5, f"close() занял {box['elapsed']:.2f}с"
    finally:
        stand.close()
