# -*- coding: utf-8 -*-
"""SocketChannel: занятый порт и переоткрытие порта после close (Win-D).

Класс ошибки: на Windows ``SO_REUSEADDR`` разрешал второму слушателю молча занять
порт живого канала (второй ``bind`` проходил), и второй PM перезаписывал токен
backend_ctl первого. Гарантии:

- второй ``start()`` на занятый порт возвращает False, первый канал продолжает
  принимать соединения (Windows и POSIX);
- после ``close()`` порт тут же переоткрывается в том же процессе — и новым
  каналом при живом соединении в момент остановки, и тем же объектом.
"""

from __future__ import annotations

import json
import socket
import time
from typing import Any

from ..channels.socket_channel import SocketChannel


def _wait(predicate, timeout: float = 2.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _send_line(sock: socket.socket, msg: dict[str, Any]) -> None:
    sock.sendall((json.dumps(msg) + "\n").encode("utf-8"))


def test_second_start_on_busy_port_fails_and_first_keeps_serving() -> None:
    received_a: list[dict[str, Any]] = []
    received_b: list[dict[str, Any]] = []
    ch_a = SocketChannel("busy_a", port=0, on_inbound=received_a.append)
    ch_b: SocketChannel | None = None
    try:
        assert ch_a.start() is True
        port = ch_a.port

        ch_b = SocketChannel("busy_b", port=port, on_inbound=received_b.append)
        assert ch_b.start() is False
        assert ch_b.get_info()["bound"] is False

        # Несколько соединений подряд: при двойном слушателе ядро отдало бы часть второму.
        for i in range(5):
            with socket.create_connection(("127.0.0.1", port), timeout=2.0) as client:
                _send_line(client, {"n": i})
                assert _wait(lambda: len(received_a) == i + 1), f"первый канал не получил сообщение {i}"
        assert [m["n"] for m in received_a] == [0, 1, 2, 3, 4]
        assert received_b == []
    finally:
        # Гасим и второй канал: если он всё-таки поднялся, его accept-поток не утечёт.
        if ch_b is not None:
            ch_b.close()
        ch_a.close()


def test_new_channel_reopens_port_after_close_with_live_connection() -> None:
    received: list[dict[str, Any]] = []
    ch1 = SocketChannel("reopen_1", port=0, on_inbound=received.append)
    ch2: SocketChannel | None = None
    try:
        assert ch1.start() is True
        port = ch1.port

        # Соединение живо в момент close(): сервер закрывает свою сторону первым.
        client = socket.create_connection(("127.0.0.1", port), timeout=2.0)
        try:
            _send_line(client, {"n": 1})
            assert _wait(lambda: len(received) == 1)
            ch1.close()

            ch2 = SocketChannel("reopen_2", port=port, on_inbound=received.append)
            assert ch2.start() is True
            assert ch2.port == port
        finally:
            client.close()

        with socket.create_connection(("127.0.0.1", port), timeout=2.0) as client2:
            _send_line(client2, {"n": 2})
            assert _wait(lambda: len(received) == 2), "новый канал на том же порту не принял соединение"
        assert received == [{"n": 1}, {"n": 2}]
    finally:
        if ch2 is not None:
            ch2.close()
        ch1.close()


def test_same_channel_restarts_on_same_port_after_close() -> None:
    received: list[dict[str, Any]] = []
    ch = SocketChannel("restart_same", port=0, on_inbound=received.append)
    try:
        assert ch.start() is True
        port = ch.port
        ch.close()

        assert ch.start() is True
        assert ch.port == port
        with socket.create_connection(("127.0.0.1", port), timeout=2.0) as client:
            _send_line(client, {"n": 7})
            assert _wait(lambda: len(received) == 1)
        assert received == [{"n": 7}]
    finally:
        ch.close()
