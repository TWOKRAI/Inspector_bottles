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


# --------------------------------------------------------------------------- (d)–(f): break-injection лида


class _StubClient:
    """Минимальный клиент без сокета: push'и вызываются тестом напрямую."""

    def __init__(self, reply: Dict[str, Any]) -> None:
        self.subscriber_address = "pult.stub"
        self.requests: list = []
        self._reply = reply
        self._listeners: list = []

    def add_push_listener(self, fn: Callable[[Dict[str, Any]], None]) -> None:
        self._listeners.append(fn)

    def request(self, message: Dict[str, Any], timeout: float = 5.0) -> Dict[str, Any]:
        self.requests.append(message)
        return dict(self._reply)

    def push(self, descriptor: Dict[str, Any]) -> None:
        for fn in self._listeners:
            fn({"type": "event", "command": "frames.frame", "data": descriptor})


def _wait(predicate: Callable[[], bool], timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_d_odd_generation_is_torn_not_delivered() -> None:
    """(d) Слот с НЕЧЁТНЫМ поколением (писатель посреди записи) при ``seqlock=True`` →
    колбэк не зовётся, ``torn == 1``. Детерминированно, без гонки писателя.

    Инъекция: ``verify_seqlock=seqlock`` → ``False`` в ``_read_noting_generation`` →
    кадр читается как целый и доставляется → красный."""
    import struct

    frame = np.full((48, 64, 3), 5, dtype=np.uint8)
    size = calculate_buffer_size(1, frame.shape, frame.dtype, seqlock=True)
    shm = shared_memory.SharedMemory(name=f"t13d{uuid.uuid4().hex[:8]}", create=True, size=size)
    source = None
    try:
        pack_images(shm.buf, [frame], frame.shape, frame.dtype, seqlock=True)
        gen = struct.unpack_from("<I", shm.buf, 0)[0]
        struct.pack_into("<I", shm.buf, 0, gen | 1)  # запись «в процессе»

        client = _StubClient({"success": True, "seqlock": True, "owner_incarnation": False})
        delivered: list = []
        source = RemoteFrameSource(client, dispatch=lambda fn: fn())  # type: ignore[arg-type]
        source.subscribe(None, lambda s, a, b: delivered.append(b))
        client.push({"sender": "camA", "name": shm.name, "idx": 0, "seqlock": True, "bseq": 1, "ts": 0.0})

        assert _wait(lambda: source.stats["torn"] + source.stats["delivered"] + source.stats["errors"] >= 1)
        assert delivered == [], "кадр с нечётным поколением доставлен как целый"
        assert source.stats["torn"] == 1, source.stats
    finally:
        if source is not None:
            _in_thread(source.close, deadline=4.0)
        shm.close()
        shm.unlink()


def test_e_unsubscribe_during_in_flight_copy_drops_the_frame() -> None:
    """(e) ``unsubscribe`` вернулся, пока поток копирования внутри ``read_frame`` →
    прочитанный ПОСЛЕ этого кадр не доставляется и считается ``superseded``.

    Инъекция: проверка эпохи перед dispatch (``if epoch != self._epoch``) → ``if False`` →
    кадр доставлен после отписки → красный."""
    client = _StubClient({"success": True, "seqlock": False, "owner_incarnation": False})
    delivered: list = []
    source = RemoteFrameSource(client, dispatch=lambda fn: fn())  # type: ignore[arg-type]
    source.subscribe(None, lambda s, a, b: delivered.append(b))

    entered = threading.Event()
    release = threading.Event()

    class _BlockingReader:
        def read_frame(self, name: str, seqlock: bool = False, **kw: Any) -> np.ndarray:
            entered.set()
            release.wait(5.0)
            return np.zeros((2, 2, 3), dtype=np.uint8)

        def close(self) -> None:
            pass

    source._reader = _BlockingReader()  # белый ящик: держим копию «в полёте»
    try:
        client.push({"sender": "camA", "name": "slot", "idx": 0, "seqlock": False, "bseq": 1, "ts": 0.0})
        assert entered.wait(3.0), "поток копирования не дошёл до read_frame"

        box = _in_thread(source.unsubscribe, deadline=3.0)
        assert not box["alive"] and "exc" not in box, box

        release.set()
        assert _wait(lambda: source.stats["superseded"] + source.stats["delivered"] >= 1), source.stats
        assert delivered == [], "кадр, дочитанный после unsubscribe, доставлен"
        assert source.stats["superseded"] == 1, source.stats
        assert source.stats["delivered"] == 0, source.stats
    finally:
        release.set()
        _in_thread(source.close, deadline=4.0)


def test_f_unsubscribe_sends_frames_unsubscribe_to_host() -> None:
    """(f) ``unsubscribe()`` доставляет хосту ``frames.unsubscribe {"subscriber": <адрес>}``
    (реальный SocketChannel-хост, канал ``backend_ctl``) — к моменту возврата.

    Инъекция: ``unsubscribe`` возвращается сразу после локального снятия, до request →
    хост ничего не получил → красный."""
    seen: list = []
    router, sock_ch = _make_host(
        {
            "frames.subscribe": lambda m: {"success": True, "seqlock": False, "owner_incarnation": False},
            "frames.unsubscribe": lambda m: seen.append(m.get("data")) or {"success": True, "removed": True},
        }
    )
    client = SocketClient("127.0.0.1", sock_ch.port, sender="backend_ctl")
    source = None
    try:
        client.connect()
        address = client.subscriber_address
        source = RemoteFrameSource(client, dispatch=lambda fn: fn())
        sub = _in_thread(lambda: source.subscribe(None, lambda s, a, b: None, timeout=3.0), deadline=4.0)
        assert not sub["alive"] and "exc" not in sub, sub

        box = _in_thread(lambda: source.unsubscribe(timeout=3.0), deadline=4.0)
        assert not box["alive"] and "exc" not in box, box
        # Транспорт хоста дописывает в data свой correlation_id — сверяем адрес, не весь dict.
        assert [d.get("subscriber") for d in seen] == [address], f"хост не получил frames.unsubscribe: {seen}"
    finally:
        if source is not None:
            _in_thread(source.close, deadline=4.0)
        client.close()
        router.shutdown()
        sock_ch.close()
