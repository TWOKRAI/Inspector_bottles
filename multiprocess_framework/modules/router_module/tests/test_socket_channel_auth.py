# -*- coding: utf-8 -*-
"""Слепая приёмка Task 0.12: рукопожатие ``hello`` с токеном (RED против заглушки).

Источник контракта — только ``plans/2026-11-21_observability-signal-contracts/tasks/0.12.md``
(блок «КОНТРАКТ ДЛЯ СЛЕПОГО TESTER» и «REDS»). Файлы ``socket_channel.py``,
``socket_client.py``, ``socket_auth.py`` не читались: тесты утверждают поведение
по контракту, а не по коду. Hazard-тесты (гонки, дочитывание после отказа) —
в ``test_socket_channel_auth_hazards.py`` (teamlead).

Литералы (токены ``"ab" * 32``, тайминги, формы строк) — из контракта, не выводятся
из кода под тестом. Каждый тест с сокетом идёт в daemon-потоке с join-дедлайном 5 с
(декоратор ``_bounded``); ожидания — опросом с таймаутом.

Проводной формат: UTF-8 JSON, строка = dict + ``\\n``.
  hello      -> {"type": "hello", "token": "<hex64>"}
  успех      -> {"type": "hello", "success": true}
  отказ      -> {"success": false, "error": "auth_required"} и EOF
                (допустимы ConnectionResetError / BrokenPipeError; по дедлайну и по
                потолку 4096 строка отказа ПЕРЕД EOF допустима — читаем до EOF).
"""

from __future__ import annotations

import functools
import json
import logging
import socket
import stat
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

import pytest

from ..channels.socket_auth import (
    file_token_provider,
    read_token,
    resolve_token_path,
    token_authenticator,
    write_token,
)
from ..channels.socket_channel import SocketChannel
from ..channels.socket_client import SocketAuthError, SocketClient

TOKEN = "ab" * 32
OTHER_TOKEN = "cd" * 32
REJECT = {"success": False, "error": "auth_required"}
ACK = {"type": "hello", "success": True}


# --------------------------------------------------------------------------- хелперы
def _bounded(join_s: float = 5.0) -> Callable:
    """Тело теста — в daemon-потоке с join-дедлайном; исключение пробрасывается сюда."""

    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            box: dict[str, Any] = {}

            def run() -> None:
                try:
                    box["result"] = fn(*args, **kwargs)
                except BaseException as exc:  # noqa: BLE001 — пробрасываем в поток pytest ниже
                    box["exc"] = exc

            t = threading.Thread(target=run, daemon=True)
            t.start()
            t.join(join_s)
            if t.is_alive():
                pytest.fail(f"тест завис: не уложился в {join_s} с")
            if "exc" in box:
                raise box["exc"]
            return box.get("result")

        return wrapper

    return deco


def _wait(predicate: Callable[[], Any], timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


def _hello(token: Any = TOKEN, **extra: Any) -> bytes:
    msg = {"type": "hello", "token": token}
    msg.update(extra)
    return json.dumps(msg, ensure_ascii=False).encode("utf-8") + b"\n"


def _line(msg: dict) -> bytes:
    return json.dumps(msg).encode("utf-8") + b"\n"


def _read_to_end(sock: socket.socket, timeout: float = 1.5) -> tuple[bytes, str]:
    """Читать до EOF. -> (данные, 'eof' | 'reset' | 'timeout'). Исключений сокета не бросает."""
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


def _read_line(sock: socket.socket, timeout: float = 1.0) -> dict | None:
    """Одна JSON-строка или None (таймаут / EOF / reset до полной строки)."""
    deadline = time.monotonic() + timeout
    buf = b""
    while b"\n" not in buf:
        left = deadline - time.monotonic()
        if left <= 0:
            return None
        sock.settimeout(left)
        try:
            chunk = sock.recv(4096)
        except (socket.timeout, ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            return None
        if not chunk:
            return None
        buf += chunk
    first = buf.split(b"\n", 1)[0]
    try:
        return json.loads(first.decode("utf-8"))
    except ValueError:
        return {"_unparsable": first}


def _parse_lines(buf: bytes) -> list[dict]:
    out: list[dict] = []
    for raw in buf.split(b"\n"):
        if not raw.strip():
            continue
        try:
            out.append(json.loads(raw.decode("utf-8")))
        except ValueError:
            out.append({"_unparsable": raw})
    return out


def _assert_rejected(buf: bytes, end: str, *, require_line: bool) -> None:
    """Отказ: соединение закрыто (EOF/reset); строки до EOF — только auth_required."""
    assert end in ("eof", "reset"), f"соединение не закрыто сервером (итог чтения: {end}, данные: {buf!r})"
    lines = _parse_lines(buf)
    for d in lines:
        assert d.get("success") is False and d.get("error") == "auth_required", f"не отказ auth_required: {d!r}"
    if require_line and end == "eof":
        assert lines, "EOF без строки отказа auth_required"


class _RawServer:
    """Сырой слушающий сокет: handler(conn, n, srv) на каждое соединение, последовательно."""

    def __init__(self, handler: Callable[[socket.socket, int, "_RawServer"], None]) -> None:
        self._handler = handler
        self._lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._lsock.bind(("127.0.0.1", 0))
        self._lsock.listen(4)
        self._lsock.settimeout(0.2)
        self.port: int = self._lsock.getsockname()[1]
        self.lines: list[dict] = []
        self.raw: bytes = b""
        self._conns: list[socket.socket] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        n = 0
        while not self._stop.is_set():
            try:
                conn, _ = self._lsock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            n += 1
            self._conns.append(conn)
            try:
                self._handler(conn, n, self)
            except Exception:  # noqa: BLE001 — сбой обработчика видит тест по пустым записям
                pass

    def readline(self, conn: socket.socket, timeout: float) -> dict | None:
        deadline = time.monotonic() + timeout
        buf = b""
        while b"\n" not in buf:
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            conn.settimeout(left)
            try:
                chunk = conn.recv(4096)
            except (socket.timeout, OSError):
                return None
            if not chunk:
                return None
            buf += chunk
        self.raw += buf
        first = buf.split(b"\n", 1)[0]
        try:
            return json.loads(first.decode("utf-8"))
        except ValueError:
            return {"_unparsable": first}

    def close(self) -> None:
        self._stop.set()
        for c in self._conns:
            try:
                c.close()
            except OSError:
                pass
        try:
            self._lsock.close()
        except OSError:
            pass


# --------------------------------------------------------------------------- фикстуры
@pytest.fixture
def make_channel():
    created: list[SocketChannel] = []

    def _make(**kw: Any):
        inbound: list[dict] = []
        warnings: list[str] = []
        errors: list[str] = []
        kw.setdefault("authenticator", token_authenticator(TOKEN))
        ch = SocketChannel(
            "auth_test",
            host="127.0.0.1",
            port=0,
            on_inbound=inbound.append,
            log_warning=lambda *a, **k: warnings.append(f"{a} {k}"),
            log_error=lambda *a, **k: errors.append(f"{a} {k}"),
            **kw,
        )
        assert ch.start() is True
        created.append(ch)
        return ch, inbound, warnings, errors

    yield _make
    for ch in created:
        try:
            ch.close()
        except Exception:  # noqa: BLE001 — уборка не должна маскировать результат теста
            pass


@pytest.fixture
def conns():
    socks: list[socket.socket] = []

    def _connect(ch: SocketChannel) -> socket.socket:
        s = socket.create_connection(("127.0.0.1", ch.port), timeout=2.0)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        socks.append(s)
        return s

    yield _connect
    for s in socks:
        try:
            s.close()
        except OSError:
            pass


@pytest.fixture
def make_client():
    made: list[SocketClient] = []

    def _make(port: int, provider: Callable[[], str | None] | None = None) -> SocketClient:
        if provider is None:
            c = SocketClient("127.0.0.1", port, sender="t")
        else:
            c = SocketClient("127.0.0.1", port, sender="t", token_provider=provider)
        made.append(c)
        return c

    yield _make
    for c in made:
        try:
            c.close()
        except Exception:  # noqa: BLE001
            pass


@pytest.fixture
def raw_server():
    servers: list[_RawServer] = []

    def _make(handler: Callable[[socket.socket, int, _RawServer], None]) -> _RawServer:
        s = _RawServer(handler)
        servers.append(s)
        return s

    yield _make
    for s in servers:
        s.close()


def _authenticate(sock: socket.socket) -> dict | None:
    sock.sendall(_hello())
    return _read_line(sock, 1.0)


# --------------------------------------------------------------------------- сервер
@_bounded()
def test_no_hello_rejected(make_channel, conns) -> None:
    # сейчас (заглушка): red(по утверждению) — authenticator игнорируется, строка уходит в on_inbound, отказа и EOF нет
    ch, inbound, _w, _e = make_channel()
    s = conns(ch)
    s.sendall(_line({"cmd": "ping"}))
    buf, end = _read_to_end(s, 1.5)
    _assert_rejected(buf, end, require_line=True)
    time.sleep(0.5)
    assert inbound == [], f"отвергнутая строка дошла до роутера: {inbound!r}"


@_bounded()
def test_wrong_token_rejected(make_channel, conns) -> None:
    # сейчас (заглушка): red(по утверждению) — неверный токен принят, отказа и EOF нет
    ch, inbound, _w, _e = make_channel()
    s = conns(ch)
    s.sendall(_hello(OTHER_TOKEN))
    buf, end = _read_to_end(s, 1.5)
    _assert_rejected(buf, end, require_line=True)
    assert _wait(lambda: ch.get_info()["auth_rejected"] == 1, 1.0), ch.get_info()
    time.sleep(0.5)
    assert inbound == []


@_bounded()
def test_good_token_passes(make_channel, conns) -> None:
    # сейчас (заглушка): red(по утверждению) — ответа на hello нет (hello уходит в on_inbound)
    ch, inbound, _w, _e = make_channel()
    s = conns(ch)
    reply = _authenticate(s)
    assert reply is not None and reply.get("type") == "hello" and reply.get("success") is True, reply
    s.sendall(_line({"cmd": "ping"}))
    assert _wait(lambda: len(inbound) >= 1, 2.0), "команда после hello не дошла до on_inbound"
    time.sleep(0.5)
    assert len(inbound) == 1 and inbound[0].get("cmd") == "ping", inbound


@_bounded()
def test_no_authenticator_keeps_old_behaviour(make_channel, conns) -> None:
    # сейчас (заглушка): green(страж) — без authenticator сокет в _clients на accept, команды и broadcast как раньше
    ch, inbound, _w, _e = make_channel(authenticator=None)
    s = conns(ch)
    assert _wait(lambda: ch.get_info()["clients"] >= 1, 2.0), "клиент не зарегистрирован на accept"
    s.sendall(_line({"cmd": "ping"}))
    assert _wait(lambda: len(inbound) == 1, 2.0), inbound
    assert inbound[0].get("cmd") == "ping"
    ch.send({"x": 1})
    got = _read_line(s, 1.5)
    assert got is not None and got.get("x") == 1, got


@_bounded()
def test_unauthenticated_client_gets_no_broadcast(make_channel, conns) -> None:
    # сейчас (заглушка): red(по утверждению) — A не получает ответа на hello (и B был бы в _clients)
    ch, _inbound, _w, _e = make_channel(hello_timeout_s=5.0)
    b = conns(ch)  # подключается первым и молчит
    time.sleep(0.1)
    a = conns(ch)
    reply = _authenticate(a)
    assert reply is not None and reply.get("success") is True, reply
    # ответ пишется ДО регистрации: ждём, пока A попадёт в рассылку
    assert _wait(lambda: ch.get_info()["clients"] >= 1, 2.0), "A не зарегистрирован после hello"
    ch.send({"bc": "hi"})
    got = _read_line(a, 1.5)
    assert got is not None and got.get("bc") == "hi", got
    b.settimeout(0.5)
    with pytest.raises(socket.timeout):
        b.recv(4096)


@_bounded()
def test_silent_client_closed_after_hello_deadline(make_channel, conns) -> None:
    # сейчас (заглушка): red(по утверждению) — дедлайна нет, молчаливый сокет не закрывается
    ch, _inbound, _w, _e = make_channel(hello_timeout_s=0.1)
    s = conns(ch)
    t0 = time.monotonic()
    buf, end = _read_to_end(s, 3.0)
    elapsed = time.monotonic() - t0
    _assert_rejected(buf, end, require_line=False)
    assert elapsed <= 3.0, f"EOF позже 3.0 с: {elapsed:.2f}"
    assert _wait(lambda: ch.get_info()["auth_rejected"] == 1, 0.5), ch.get_info()


@_bounded()
def test_silent_client_does_not_block_second_client(make_channel, conns) -> None:
    # сейчас (заглушка): red(по утверждению) — второй клиент не получает ответа на hello
    ch, _inbound, _w, _e = make_channel()
    conns(ch)  # первый молчит
    time.sleep(0.1)
    second = conns(ch)
    t0 = time.monotonic()
    second.sendall(_hello())
    reply = _read_line(second, 1.0)
    elapsed = time.monotonic() - t0
    assert reply is not None and reply.get("success") is True, reply
    assert elapsed < 1.0, f"hello второго клиента занял {elapsed:.2f} с"


@_bounded()
def test_dripping_client_closed_after_hello_deadline(make_channel, conns) -> None:
    # сейчас (заглушка): red(по утверждению) — дедлайна нет, байт раз в 0.1 с держит соединение
    ch, _inbound, _w, _e = make_channel(hello_timeout_s=0.1)
    s = conns(ch)
    t0 = time.monotonic()
    closed = False
    received = b""
    while time.monotonic() - t0 < 3.0 and not closed:
        try:
            s.sendall(b"x")
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            closed = True
            break
        s.settimeout(0.1)  # заодно пауза между байтами
        try:
            chunk = s.recv(4096)
        except socket.timeout:
            continue
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            closed = True
            break
        if not chunk:
            closed = True
            break
        received += chunk
    assert closed, "соединение с капающим клиентом не закрыто за 3.0 с"
    for d in _parse_lines(received):
        assert d.get("success") is False and d.get("error") == "auth_required", d


@_bounded()
def test_hello_without_token_rejected(make_channel, conns) -> None:
    # сейчас (заглушка): red(по утверждению) — hello без token принят, отказа и EOF нет
    ch, inbound, _w, _e = make_channel()
    s = conns(ch)
    s.sendall(_line({"type": "hello"}))
    buf, end = _read_to_end(s, 1.5)
    _assert_rejected(buf, end, require_line=True)
    time.sleep(0.5)
    assert inbound == []


@pytest.mark.parametrize("bad", ["é", None, 123, ["x"]], ids=["non-ascii", "none", "int", "list"])
@_bounded()
def test_hello_non_ascii_token_rejected(make_channel, conns, bad: Any) -> None:
    # сейчас (заглушка): red(по утверждению) — враждебный токен принят, отказа и EOF нет
    ch, inbound, _w, _e = make_channel()
    s = conns(ch)
    s.sendall(_hello(bad))
    buf, end = _read_to_end(s, 1.5)
    _assert_rejected(buf, end, require_line=True)
    assert inbound == []
    # сервер жив: следующее соединение с верным токеном проходит
    s2 = conns(ch)
    reply = _authenticate(s2)
    assert reply is not None and reply.get("success") is True, reply


@_bounded()
def test_hello_split_across_segments(make_channel, conns) -> None:
    # сейчас (заглушка): red(по утверждению) — ответа на hello нет
    ch, inbound, _w, _e = make_channel()
    s = conns(ch)
    data = _hello()
    third = len(data) // 3
    for chunk in (data[:third], data[third : 2 * third], data[2 * third :]):
        s.sendall(chunk)
        time.sleep(0.1)
    reply = _read_line(s, 1.0)
    assert reply is not None and reply.get("type") == "hello" and reply.get("success") is True, reply
    s.sendall(_line({"cmd": "ping"}))
    assert _wait(lambda: len(inbound) == 1, 2.0), inbound
    assert inbound[0].get("cmd") == "ping"


@_bounded()
def test_hello_and_command_in_one_segment(make_channel, conns) -> None:
    # сейчас (заглушка): red(по утверждению) — нет ответа на верный hello; плохой hello + команда уходят в on_inbound
    ch, inbound, _w, _e = make_channel()
    # верный hello + команда одним send: ответ, затем команда в on_inbound
    good = conns(ch)
    good.sendall(_hello() + _line({"cmd": "ping"}))
    reply = _read_line(good, 1.0)
    assert reply is not None and reply.get("type") == "hello" and reply.get("success") is True, reply
    assert _wait(lambda: len(inbound) == 1, 2.0), inbound
    assert inbound[0].get("cmd") == "ping"
    del inbound[:]
    # плохой hello + команда одним send: отказ, команда в роутер не уходит
    bad = conns(ch)
    bad.sendall(_hello(OTHER_TOKEN) + _line({"cmd": "evil"}))
    buf, end = _read_to_end(bad, 1.5)
    _assert_rejected(buf, end, require_line=True)
    time.sleep(0.5)
    assert inbound == [], f"команда после плохого hello дошла до роутера: {inbound!r}"


@pytest.mark.parametrize("garbage", [b"\xff\xfe\n", b"[1]\n"], ids=["bad-utf8", "json-list"])
@_bounded()
def test_first_line_garbage_rejected(make_channel, conns, garbage: bytes) -> None:
    # сейчас (заглушка): red(по утверждению) — мусорная первая строка пропущена, соединение не закрыто
    ch, inbound, _w, _e = make_channel()
    s = conns(ch)
    s.sendall(garbage)
    buf, end = _read_to_end(s, 1.5)
    _assert_rejected(buf, end, require_line=False)
    time.sleep(0.5)
    assert inbound == []


@_bounded()
def test_oversize_first_line_rejected(make_channel, conns) -> None:
    # сейчас (заглушка): red(по утверждению) — потолка 4096 нет, соединение не закрыто
    ch, inbound, _w, _e = make_channel(hello_timeout_s=5.0)
    s = conns(ch)
    s.sendall(b"a" * 5000)  # без \n
    t0 = time.monotonic()
    buf, end = _read_to_end(s, 3.0)
    elapsed = time.monotonic() - t0
    _assert_rejected(buf, end, require_line=False)
    assert elapsed < 4.0, f"отказ позже, чем за дедлайн hello (5 с): {elapsed:.2f}"
    assert inbound == []


@_bounded()
def test_authenticator_exception_rejected(make_channel, conns) -> None:
    # сейчас (заглушка): red(по утверждению) — authenticator не вызывается, отказа нет
    calls: list[int] = []
    real = token_authenticator(TOKEN)

    def flaky(msg: dict) -> bool:
        calls.append(1)
        if len(calls) == 1:
            1 / 0  # noqa: B018 — исключение authenticator на первом вызове
        return real(msg)

    ch, inbound, _w, errors = make_channel(authenticator=flaky)
    s = conns(ch)
    s.sendall(_hello("SECRET-xyz"))
    buf, end = _read_to_end(s, 1.5)
    _assert_rejected(buf, end, require_line=True)
    assert _wait(lambda: len(errors) >= 1, 1.0), "исключение authenticator не залогировано как ERROR"
    assert "SECRET-xyz" not in " ".join(errors), "в ERROR попало содержимое строки"
    assert inbound == []
    # следующий клиент проходит
    s2 = conns(ch)
    reply = _authenticate(s2)
    assert reply is not None and reply.get("success") is True, reply


@_bounded()
def test_repeated_hello_after_success_goes_to_on_inbound(make_channel, conns) -> None:
    # сейчас (заглушка): red(по утверждению) — на первый hello нет ответа; on_inbound получает 2 вызова, ждём 1
    ch, inbound, _w, _e = make_channel()
    s = conns(ch)
    reply = _authenticate(s)
    assert reply is not None and reply.get("success") is True, reply
    s.sendall(_hello(n=2))
    assert _wait(lambda: len(inbound) >= 1, 2.0), "повторный hello не дошёл до on_inbound"
    time.sleep(0.5)
    assert len(inbound) == 1, inbound
    assert inbound[0].get("type") == "hello" and inbound[0].get("n") == 2
    assert "token" not in inbound[0], "токен дошёл до роутера"


@pytest.mark.parametrize("bad", [0, -1])
def test_hello_timeout_non_positive_raises(bad: int) -> None:
    # сейчас (заглушка): red(по утверждению) — параметр принят и проигнорирован, ValueError не бросается
    with pytest.raises(ValueError):
        SocketChannel(
            "auth_test",
            host="127.0.0.1",
            port=0,
            authenticator=token_authenticator(TOKEN),
            hello_timeout_s=bad,
        )


@_bounded()
def test_hello_to_open_server_is_acknowledged(make_channel, conns) -> None:
    # сейчас (заглушка): red(по утверждению) — hello уходит в on_inbound, ответа нет
    ch, inbound, _w, _e = make_channel(authenticator=None)
    s = conns(ch)
    reply = _authenticate(s)
    assert reply is not None and reply.get("type") == "hello" and reply.get("success") is True, reply
    time.sleep(0.5)
    assert inbound == [], f"hello открытого сервера ушёл в on_inbound: {inbound!r}"


# --------------------------------------------------------------------------- клиент
@_bounded()
def test_client_without_provider_gets_auth_required(make_channel, make_client) -> None:
    # сейчас (заглушка): red(по утверждению) — сервер не отвечает на команду, request кончается таймаутом
    ch, _inbound, _w, _e = make_channel()
    client = make_client(ch.port)
    try:
        client.connect(timeout=2.0)
        outcome: Any = client.request({"cmd": "ping"}, timeout=1.5)
    except Exception as exc:  # noqa: BLE001 — исход разбирается утверждением ниже
        outcome = exc
    assert isinstance(outcome, dict), f"request не вернул ответ-отказ: {outcome!r}"
    assert outcome.get("success") is False and outcome.get("error") == "auth_required", outcome
    assert outcome.get("request_id"), "в отказе нет эха request_id"


@_bounded()
def test_client_sends_hello_first_when_provider_returns_token(make_client, raw_server) -> None:
    # сейчас (заглушка): red(по утверждению) — клиент не шлёт hello, первых байт на сокете нет
    def handler(conn: socket.socket, n: int, srv: _RawServer) -> None:
        msg = srv.readline(conn, 2.0)
        if msg is not None:
            srv.lines.append(msg)
            conn.sendall(_line(ACK))

    srv = raw_server(handler)
    client = make_client(srv.port, lambda: TOKEN)
    try:
        client.connect(timeout=2.0)
    except Exception:  # noqa: BLE001 — исход видим по записям сырого сервера
        pass
    assert _wait(lambda: srv.lines, 1.0), "клиент не прислал ни одной строки при connect"
    first = srv.lines[0]
    assert first.get("type") == "hello" and first.get("token") == TOKEN, first


@_bounded()
def test_provider_none_sends_no_hello(make_client, raw_server) -> None:
    # сейчас (заглушка): green(страж) — без токена hello не шлётся, первые байты — сама команда
    def handler(conn: socket.socket, n: int, srv: _RawServer) -> None:
        msg = srv.readline(conn, 2.0)
        if msg is not None:
            srv.lines.append(msg)

    srv = raw_server(handler)
    client = make_client(srv.port, lambda: None)
    client.connect(timeout=2.0)  # без hello сырой сервер ничего не отвечает, connect не ждёт
    try:
        client.request({"cmd": "ping"}, timeout=0.5)  # ответа не будет: нужны лишь первые байты
    except Exception:  # noqa: BLE001
        pass
    assert _wait(lambda: srv.lines, 1.5), "на сокет не пришло ни одной строки"
    first = srv.lines[0]
    assert first.get("type") != "hello" and "token" not in first, first
    assert b"ping" in srv.raw, "первая строка — не команда клиента"


@_bounded()
def test_client_auth_error_is_oserror(make_channel, make_client) -> None:
    # сейчас (заглушка): red(по утверждению) — клиент не шлёт hello, connect проходит, SocketAuthError не брошен
    ch, _inbound, _w, _e = make_channel()
    wrong = OTHER_TOKEN
    client = make_client(ch.port, lambda: wrong)
    try:
        client.connect(timeout=2.0)
        outcome: BaseException | None = None
    except Exception as exc:  # noqa: BLE001
        outcome = exc
    assert isinstance(outcome, SocketAuthError), f"ожидался SocketAuthError, получено {outcome!r}"
    assert isinstance(outcome, OSError)
    assert wrong not in str(outcome), "токен попал в текст исключения"


@_bounded()
def test_hello_ack_not_delivered_as_push(make_client, raw_server) -> None:
    # сейчас (заглушка): red(по утверждению) — hello не приходит, сырой сервер молчит, request кончается таймаутом
    def handler(conn: socket.socket, n: int, srv: _RawServer) -> None:
        first = srv.readline(conn, 2.0)
        if first is None or first.get("type") != "hello":
            return
        conn.sendall(_line(ACK))
        second = srv.readline(conn, 3.0)
        if second is not None:
            conn.sendall(_line({"success": True, "request_id": second.get("request_id")}))

    srv = raw_server(handler)
    pushes: list[Any] = []
    client = make_client(srv.port, lambda: TOKEN)
    client.add_push_listener(pushes.append)
    try:
        client.connect(timeout=2.0)
        outcome: Any = client.request({"cmd": "ping"}, timeout=1.5)
    except Exception as exc:  # noqa: BLE001
        outcome = exc
    assert isinstance(outcome, dict) and outcome.get("success") is True, f"request не успешен: {outcome!r}"
    time.sleep(0.3)
    assert pushes == [], f"ответ hello доставлен как push: {pushes!r}"


@_bounded()
def test_client_rejects_ack_without_hello_type(make_client, raw_server) -> None:
    # сейчас (заглушка): red(по утверждению) — клиент не шлёт hello и не проверяет ответ, SocketAuthError не брошен
    def handler(conn: socket.socket, n: int, srv: _RawServer) -> None:
        first = srv.readline(conn, 2.0)
        if first is not None:
            conn.sendall(_line({"success": True}))  # без "type": чужая рассылка

    srv = raw_server(handler)
    client = make_client(srv.port, lambda: TOKEN)
    try:
        client.connect(timeout=2.0)
        outcome: BaseException | None = None
    except Exception as exc:  # noqa: BLE001
        outcome = exc
    assert isinstance(outcome, SocketAuthError), f"ожидался SocketAuthError, получено {outcome!r}"


@_bounded()
def test_connect_timeout_leaves_state_clean(make_client, raw_server) -> None:
    # сейчас (заглушка): red(по утверждению) — клиент не ждёт ответа hello, connect проходит без TimeoutError
    def handler(conn: socket.socket, n: int, srv: _RawServer) -> None:
        first = srv.readline(conn, 2.0)
        if first is None:
            return
        srv.lines.append(first)
        if n >= 2:  # второе соединение — исправный сервер; первое молчит (сокет остаётся открытым)
            conn.sendall(_line(ACK))

    srv = raw_server(handler)
    client = make_client(srv.port, lambda: TOKEN)
    t0 = time.monotonic()
    try:
        client.connect(timeout=0.5)
        outcome: BaseException | None = None
    except Exception as exc:  # noqa: BLE001
        outcome = exc
    elapsed = time.monotonic() - t0
    assert isinstance(outcome, TimeoutError), f"ожидался TimeoutError, получено {outcome!r}"
    assert elapsed <= 3.0, f"connect вернулся за {elapsed:.2f} с"
    assert client.session is None, "состояние не как до вызова: session задан"
    client.connect(timeout=2.0)  # повторный connect к исправному серверу проходит


# --------------------------------------------------------------------------- socket_auth
@pytest.mark.skipif(sys.platform == "win32", reason="chmod на Windows не действует: защищает ACL (plan.md, риск 0.12)")
def test_token_file_mode_0600(tmp_path: Path) -> None:
    # сейчас (заглушка): red(по утверждению) — write_token ничего не пишет и возвращает ""
    target = tmp_path / "newdir" / "ctl_1.token"
    token = write_token(target)
    assert target.exists(), "файл токена не создан"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700
    assert len(token) == 64 and all(c in "0123456789abcdef" for c in token), token
    assert target.read_text().strip() == token


@pytest.mark.parametrize(
    "msg",
    [
        {"token": "é"},
        {"token": None},
        {"token": 123},
        {"token": ["x"]},
        {"token": ""},
        {},
        {"token": OTHER_TOKEN},
    ],
    ids=["non-ascii", "none", "int", "list", "empty", "missing", "wrong-str"],
)
def test_token_authenticator_hostile_input(msg: dict) -> None:
    # сейчас (заглушка): red(по утверждению) — заглушка принимает всё (True)
    auth = token_authenticator(TOKEN)
    assert auth(msg) is False


def test_token_authenticator_good_token_and_empty_expected() -> None:
    # сейчас (заглушка): red(по утверждению) — токен "" при создании не даёт ValueError
    assert token_authenticator(TOKEN)({"token": TOKEN}) is True
    with pytest.raises(ValueError):
        token_authenticator("")


def test_token_authenticator_callable_reads_each_hello() -> None:
    # сейчас (заглушка): red(по утверждению) — заглушка отвечает True при токене None
    state: dict[str, str | None] = {"v": None}
    auth = token_authenticator(lambda: state["v"])
    assert auth({"token": TOKEN}) is False  # callable вернул None -> закрыто по умолчанию
    state["v"] = TOKEN
    assert auth({"token": TOKEN}) is True  # callable читается на КАЖДЫЙ hello
    state["v"] = OTHER_TOKEN
    assert auth({"token": TOKEN}) is False


def test_resolve_token_path_env_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # сейчас (заглушка): red(по утверждению) — возвращается Path("unset")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    explicit = tmp_path / "custom" / "x.token"
    assert resolve_token_path(8765, {"BACKEND_CTL_TOKEN_FILE": str(explicit)}) == explicit
    # env=None -> os.environ
    monkeypatch.setenv("BACKEND_CTL_TOKEN_FILE", str(explicit))
    assert resolve_token_path(8765) == explicit
    # expanduser
    assert resolve_token_path(8765, {"BACKEND_CTL_TOKEN_FILE": "~/x.token"}) == tmp_path / "x.token"


def test_resolve_token_path_default_and_empty_env_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # сейчас (заглушка): red(по утверждению) — возвращается Path("unset")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    expected = tmp_path / ".multiprocess_framework" / "ctl_8765.token"
    assert resolve_token_path(8765, {}) == expected
    assert resolve_token_path(8765, {"BACKEND_CTL_TOKEN_FILE": ""}) == expected
    assert resolve_token_path(9000, {}) == tmp_path / ".multiprocess_framework" / "ctl_9000.token"


def test_read_token_variants(tmp_path: Path) -> None:
    # сейчас (заглушка): red(по утверждению) — заглушка всегда None: красный на strip и на каталоге
    empty = tmp_path / "empty.token"
    empty.write_text("")
    blank = tmp_path / "blank.token"
    blank.write_text("  \n")
    padded = tmp_path / "padded.token"
    padded.write_text("  " + "ab" * 32 + "\n")
    assert read_token(empty) is None
    assert read_token(blank) is None
    assert read_token(padded) == "ab" * 32
    assert read_token(tmp_path / "missing.token") is None
    a_dir = tmp_path / "a_dir"
    a_dir.mkdir()
    with pytest.raises(OSError):  # прочие OSError пробрасываются (каталог вместо файла)
        read_token(a_dir)


def test_file_token_provider_rereads(tmp_path: Path) -> None:
    # сейчас (заглушка): red(по утверждению) — заглушка всегда None
    path = tmp_path / "ctl.token"
    provider = file_token_provider(8765, {"BACKEND_CTL_TOKEN_FILE": str(path)})
    path.write_text("aa" * 32)
    assert provider() == "aa" * 32
    path.write_text("bb" * 32 + "\n")
    assert provider() == "bb" * 32  # без кэша: рестарт сервера меняет токен
    path.unlink()
    assert provider() is None


@_bounded()
def test_token_never_logged(make_channel, make_client, conns, caplog: pytest.LogCaptureFixture) -> None:
    # сейчас (заглушка): red(по утверждению) — предусловие: auth_rejected == 0, SocketAuthError не брошен
    caplog.set_level(logging.DEBUG)
    ch, _inbound, warnings, errors = make_channel(authenticator=token_authenticator(OTHER_TOKEN))
    secret_a = "ab" * 32
    secret_b = "SECRET-xyz"
    # неверный токен A — сырым сокетом, читаем ответ
    s = conns(ch)
    s.sendall(_hello(secret_a))
    response, _end = _read_to_end(s, 1.5)
    # неверный токен B — клиентом, смотрим текст SocketAuthError
    client = make_client(ch.port, lambda: secret_b)
    try:
        client.connect(timeout=2.0)
        exc: BaseException | None = None
    except Exception as e:  # noqa: BLE001
        exc = e
    # предусловия: отказы действительно случились
    assert _wait(lambda: ch.get_info()["auth_rejected"] == 2, 2.0), ch.get_info()
    assert isinstance(exc, SocketAuthError), f"ожидался SocketAuthError, получено {exc!r}"
    haystacks = {
        "журнал warning": " ".join(warnings),
        "журнал error": " ".join(errors),
        "logging": caplog.text,
        "текст SocketAuthError": str(exc),
        "ответ сервера": response.decode("utf-8", "replace"),
    }
    for secret in (secret_a, secret_b):
        for where, text in haystacks.items():
            assert secret not in text, f"токен {secret!r} найден: {where}"
