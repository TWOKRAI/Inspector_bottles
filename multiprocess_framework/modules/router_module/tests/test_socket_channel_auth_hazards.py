# -*- coding: utf-8 -*-
"""Hazard-тесты рукопожатия Task 0.12 (автор — исполнитель, teamlead).

Гонки и ресурсы, которых нет в слепой приёмке ``test_socket_channel_auth.py``:
враждебный токен не роняет read-поток, первая строка с ``session`` не попадает в
``_sessions``, молчуны не держат ``close()``, отказ при непрочитанном хвосте не теряет
ответ, дочитывание после отказа ограничено по времени и не держит рассылку.
Каждый тест с сокетом — в daemon-потоке с join 5 с.
"""

from __future__ import annotations

import functools
import json
import socket
import threading
import time
from typing import Any, Callable

import pytest

from ..channels.socket_auth import token_authenticator
from ..channels.socket_channel import SocketChannel

TOKEN = "ab" * 32
OTHER_TOKEN = "cd" * 32


def _bounded(fn: Callable) -> Callable:
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        box: dict[str, Any] = {}

        def run() -> None:
            try:
                fn(*args, **kwargs)
            except BaseException as exc:  # noqa: BLE001 — пробрасываем в поток pytest
                box["exc"] = exc

        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(5.0)
        if t.is_alive():
            pytest.fail("тест завис: не уложился в 5 с")
        if "exc" in box:
            raise box["exc"]

    return wrapper


def _line(msg: dict, *, ascii_only: bool = True) -> bytes:
    return json.dumps(msg, ensure_ascii=ascii_only).encode("utf-8") + b"\n"


def _read_to_end(sock: socket.socket, timeout: float) -> tuple[bytes, str]:
    deadline = time.monotonic() + timeout
    buf = b""
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            return buf, "timeout"
        sock.settimeout(left)
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            return buf, "timeout"
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            return buf, "reset"
        if not chunk:
            return buf, "eof"
        buf += chunk


def _read_line(sock: socket.socket, timeout: float) -> dict | None:
    deadline = time.monotonic() + timeout
    buf = b""
    while b"\n" not in buf:
        left = deadline - time.monotonic()
        if left <= 0:
            return None
        sock.settimeout(left)
        try:
            chunk = sock.recv(4096)
        except (socket.timeout, OSError):
            return None
        if not chunk:
            return None
        buf += chunk
    return json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))


def _is_reject_only(buf: bytes) -> bool:
    lines = [json.loads(r) for r in buf.split(b"\n") if r.strip()]
    return all(d == {"success": False, "error": "auth_required"} for d in lines)


@pytest.fixture
def env():
    made: list[Any] = []

    def channel(**kw: Any) -> tuple[SocketChannel, list[dict], list[str]]:
        inbound: list[dict] = []
        errors: list[str] = []
        kw.setdefault("authenticator", token_authenticator(TOKEN))
        ch = SocketChannel(
            "auth_hz", host="127.0.0.1", port=0, on_inbound=inbound.append, log_error=errors.append, **kw
        )
        assert ch.start() is True
        made.append(ch)
        return ch, inbound, errors

    def connect(ch: SocketChannel) -> socket.socket:
        s = socket.create_connection(("127.0.0.1", ch.port), timeout=2.0)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        made.append(s)
        return s

    yield channel, connect
    for obj in made:
        try:
            obj.close()
        except Exception:  # noqa: BLE001 — уборка
            pass


def _authenticated(connect: Callable, ch: SocketChannel) -> socket.socket:
    s = connect(ch)
    s.sendall(_line({"type": "hello", "token": TOKEN}))
    reply = _read_line(s, 1.0)
    assert reply is not None and reply.get("success") is True, reply
    return s


@pytest.mark.parametrize("bad", ["é", None, "\ud800"], ids=["non-ascii", "none", "lone-surrogate"])
@_bounded
def test_hostile_token_keeps_read_thread_alive(env, monkeypatch: pytest.MonkeyPatch, bad: Any) -> None:
    channel, connect = env
    crashed: list[Any] = []
    monkeypatch.setattr(threading, "excepthook", crashed.append)
    ch, inbound, errors = channel()
    s = connect(ch)
    s.sendall(_line({"type": "hello", "token": bad}))
    buf, end = _read_to_end(s, 1.5)
    assert end in ("eof", "reset") and _is_reject_only(buf), (end, buf)
    assert crashed == [], f"read-поток упал: {crashed!r}"
    assert errors == [], f"authenticator бросил исключение: {errors!r}"
    assert inbound == []
    _authenticated(connect, ch)


def test_lone_surrogate_token_is_false_without_exception() -> None:
    assert token_authenticator(TOKEN)({"token": "\ud800"}) is False


@_bounded
def test_first_line_with_session_not_bound(env) -> None:
    channel, connect = env
    ch, inbound, _errors = channel(session_isolation=True)
    for first in ({"cmd": "x", "session": "s-cmd"}, {"type": "hello", "token": OTHER_TOKEN, "session": "s-bad"}):
        s = connect(ch)
        s.sendall(_line(first))
        _buf, end = _read_to_end(s, 1.5)
        assert end in ("eof", "reset")
    assert ch.get_info()["sessions"] == 0, ch.get_info()
    assert ch.send({"session": "s-cmd", "x": 1})["status"] == "error"
    assert inbound == []


@_bounded
def test_silent_clients_do_not_hold_close(env) -> None:
    channel, connect = env
    ch, _inbound, _errors = channel(hello_timeout_s=5.0)
    silent = [connect(ch) for _ in range(8)]
    time.sleep(0.2)
    t0 = time.monotonic()
    ch.close()
    assert time.monotonic() - t0 < 1.5, "close() задержан молчунами"
    for s in silent:
        _buf, end = _read_to_end(s, 1.5)
        assert end in ("eof", "reset"), f"молчун не закрыт close(): {end}"
    assert time.monotonic() - t0 < 2.5


@_bounded
def test_reject_with_unread_tail_reply_or_eof(env) -> None:
    channel, connect = env
    ch, inbound, _errors = channel()
    s = connect(ch)
    s.sendall(_line({"type": "hello", "token": OTHER_TOKEN}) + b"x" * 20000)
    buf, end = _read_to_end(s, 2.0)
    assert end in ("eof", "reset"), end
    assert _is_reject_only(buf), buf
    assert end == "eof" or buf, "RST без строки отказа: клиент потерял ответ"
    assert inbound == []


@_bounded
def test_drain_bounded_for_streaming_client(env) -> None:
    channel, connect = env
    ch, _inbound, _errors = channel()
    good = _authenticated(connect, ch)
    wait_until = time.monotonic() + 2.0
    while ch.get_info()["clients"] < 1 and time.monotonic() < wait_until:
        time.sleep(0.01)  # ответ hello пишется ДО регистрации
    assert ch.get_info()["clients"] == 1
    s = connect(ch)
    s.sendall(_line({"type": "hello", "token": OTHER_TOKEN}))
    t0 = time.monotonic()
    assert _read_line(s, 1.0) == {"success": False, "error": "auth_required"}
    # отказ отправлен, сервер дочитывает — рассылка другим его не ждёт
    sent_at = time.monotonic()
    result = ch.send({"bc": 1})
    assert time.monotonic() - sent_at < 0.2, "send() ждал дочитывания"
    assert result["status"] == "success", result
    got = _read_line(good, 0.5)
    assert got is not None and got.get("bc") == 1, got
    failed_at: float | None = None
    while time.monotonic() - t0 < 3.0:
        try:
            s.send(b"x")
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            failed_at = time.monotonic() - t0
            break
        time.sleep(0.05)
    assert failed_at is not None and failed_at <= 2.0, f"дочитывание не ограничено: {failed_at}"
