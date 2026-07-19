# -*- coding: utf-8 -*-
"""Тесты SocketChannel (loopback TCP).

Покрываем:
- свойства name/channel_type; интерфейс IMessageChannel;
- start/close; bind на свободный порт (port=0);
- INBOUND: клиент шлёт newline-JSON → on_inbound получает dict;
- битая строка не роняет read-loop (skip), следующая валидная — доходит;
- non-dict сообщение игнорируется;
- OUTBOUND: send() пишет клиенту newline-JSON; нет клиентов → error;
- конкурентная запись под Lock не ломает кадры;
- get_info содержит счётчики rx/tx/clients/bound.
"""

from __future__ import annotations

import json
import socket
import time
from typing import Any, Dict, List

import pytest

from ..channels.socket_channel import SocketChannel


# --- helpers ---


def _connect(ch: SocketChannel, timeout: float = 2.0) -> socket.socket:
    """Подключиться к каналу и дождаться регистрации клиента на сервере."""
    c = socket.create_connection((ch.host, ch.port), timeout=timeout)
    c.settimeout(timeout)
    deadline = time.time() + timeout
    while ch.get_info()["clients"] < 1 and time.time() < deadline:
        time.sleep(0.01)
    return c


def _connect_nth(ch: SocketChannel, n: int, timeout: float = 2.0) -> socket.socket:
    """Подключить очередного клиента и дождаться, пока сервер учтёт всех ``n``."""
    c = socket.create_connection((ch.host, ch.port), timeout=timeout)
    c.settimeout(timeout)
    deadline = time.time() + timeout
    while ch.get_info()["clients"] < n and time.time() < deadline:
        time.sleep(0.01)
    return c


def _wait(predicate, timeout: float = 2.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _recv_line(sock: socket.socket, timeout: float = 2.0) -> Dict[str, Any]:
    """Прочитать одну newline-JSON строку из сокета."""
    sock.settimeout(timeout)
    buf = b""
    while b"\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
    line, _, _ = buf.partition(b"\n")
    return json.loads(line.decode("utf-8"))


# --- fixtures ---


@pytest.fixture
def inbound() -> List[Dict[str, Any]]:
    return []


@pytest.fixture
def channel(inbound: List[Dict[str, Any]]):
    ch = SocketChannel("backend_ctl", host="127.0.0.1", port=0, on_inbound=inbound.append)
    assert ch.start() is True
    yield ch
    ch.close()


# --- интерфейс ---


class TestInterface:
    def test_name_and_type(self, channel: SocketChannel) -> None:
        assert channel.name == "backend_ctl"
        assert channel.channel_type == "socket"

    def test_poll_is_noop(self, channel: SocketChannel) -> None:
        assert channel.poll() == []
        assert channel.poll(timeout=0.1) == []

    def test_bound_on_free_port(self, channel: SocketChannel) -> None:
        assert channel.port > 0
        assert channel.get_info()["bound"] is True

    def test_double_start_returns_false(self, channel: SocketChannel) -> None:
        assert channel.start() is False


# --- INBOUND ---


class TestInbound:
    def test_receives_newline_json(self, channel: SocketChannel, inbound: List[Dict[str, Any]]) -> None:
        c = _connect(channel)
        c.sendall(b'{"type":"command","command":"x"}\n')
        assert _wait(lambda: len(inbound) == 1)
        assert inbound[0] == {"type": "command", "command": "x"}
        c.close()

    def test_multiple_messages_one_chunk(self, channel: SocketChannel, inbound: List[Dict[str, Any]]) -> None:
        c = _connect(channel)
        c.sendall(b'{"a":1}\n{"a":2}\n')
        assert _wait(lambda: len(inbound) == 2)
        assert [m["a"] for m in inbound] == [1, 2]
        c.close()

    def test_bad_line_skipped_then_valid(self, channel: SocketChannel, inbound: List[Dict[str, Any]]) -> None:
        c = _connect(channel)
        c.sendall(b'not json at all\n{"ok":true}\n')
        assert _wait(lambda: len(inbound) == 1)
        assert inbound[0] == {"ok": True}
        c.close()

    def test_non_dict_ignored(self, channel: SocketChannel, inbound: List[Dict[str, Any]]) -> None:
        c = _connect(channel)
        c.sendall(b'[1,2,3]\n{"ok":1}\n')
        assert _wait(lambda: len(inbound) == 1)
        assert inbound[0] == {"ok": 1}
        c.close()

    def test_rx_counter(self, channel: SocketChannel, inbound: List[Dict[str, Any]]) -> None:
        c = _connect(channel)
        c.sendall(b'{"a":1}\n')
        assert _wait(lambda: channel.get_info()["rx"] == 1)
        c.close()


# --- OUTBOUND ---


class TestOutbound:
    def test_send_writes_to_client(self, channel: SocketChannel) -> None:
        c = _connect(channel)
        res = channel.send({"type": "response", "result": {"ok": True}})
        assert res["status"] == "success"
        got = _recv_line(c)
        assert got == {"type": "response", "result": {"ok": True}}
        c.close()

    def test_send_no_clients_error(self, channel: SocketChannel) -> None:
        res = channel.send({"x": 1})
        assert res["status"] == "error"
        assert "no clients" in res["reason"]

    def test_concurrent_send_keeps_frames(self, channel: SocketChannel) -> None:
        import threading

        c = _connect(channel)
        n = 50

        def worker(i: int) -> None:
            channel.send({"i": i})

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Считать n строк — каждая должна быть валидным JSON (кадры не перемешаны).
        c.settimeout(2.0)
        buf = b""
        seen = 0
        deadline = time.time() + 2.0
        while seen < n and time.time() < deadline:
            try:
                chunk = c.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if line.strip():
                    obj = json.loads(line.decode("utf-8"))  # не должно бросить
                    assert "i" in obj
                    seen += 1
        assert seen == n
        c.close()

    def test_tx_counter(self, channel: SocketChannel) -> None:
        c = _connect(channel)
        channel.send({"a": 1})
        assert channel.get_info()["tx"] >= 1
        c.close()


# --- broadcast characterization (D.1: пин ДО session-isolation) ---


class TestBroadcastCharacterization:
    """Пин текущего fan-out ПЕРЕД вводом session-isolation (D.1, §10).

    Гарантия back-compat: после ввода флага `session_isolation` при default-off
    (и для сообщений без `session`) `send()` обязан остаться broadcast'ом на всех
    подключённых клиентов. Существующие OUTBOUND-тесты используют ОДИН сокет —
    этот фиксирует именно рассылку на N>1 и счётчик `clients` в ответе.
    """

    def test_send_broadcasts_to_all_connected_clients(self, channel: SocketChannel) -> None:
        c1 = _connect_nth(channel, 1)
        c2 = _connect_nth(channel, 2)
        res = channel.send({"type": "event", "command": "state.changed", "data": {"v": 1}})
        assert res["status"] == "success"
        assert res["clients"] == 2  # fan-out на обоих
        assert _recv_line(c1)["data"] == {"v": 1}
        assert _recv_line(c2)["data"] == {"v": 1}
        c1.close()
        c2.close()


# --- lifecycle ---


class TestLifecycle:
    def test_close_is_idempotent(self) -> None:
        ch = SocketChannel("bc", host="127.0.0.1", port=0)
        ch.start()
        ch.close()
        ch.close()  # повторный close не падает
        assert ch.get_info()["bound"] is False

    def test_get_info_shape(self, channel: SocketChannel) -> None:
        info = channel.get_info()
        for key in ("name", "type", "active", "bound", "host", "port", "clients", "rx", "tx"):
            assert key in info
