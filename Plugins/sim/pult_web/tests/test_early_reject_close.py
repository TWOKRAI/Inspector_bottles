# -*- coding: utf-8 -*-
"""Механизм закрытия соединения после РАННЕГО отказа пульта (флейк pult-flake, 2026-09-29).

Ранний отказ — сервер отвечает 400/403/404/413/415 НЕ прочитав тело запроса. Если к
``close()`` в приёмном буфере сокета остались непрочитанные байты (или они приходят
ПОСЛЕ закрытия — клиент шлёт заголовки и тело двумя ``send``), Windows шлёт RST, и
клиент видит ``WinError 10053/10054`` вместо ответа. Один общий механизм закрытия
обязан доставить ответ на КАЖДЫЙ такой путь.

Тест ходит по настоящему сокету и повторяет семейство отказов ``_ROUNDS`` раз —
прежний ~1 сбой на 3-4 прогона набора становится десятками сбоев на прогон.
Клиент ведёт себя как настоящий HTTP-клиент: заголовки и тело — двумя отправками,
затем чтение до EOF. Ничего не ловится и не повторяется: любое исключение на сокете
— провал (в счёт сбоев).
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Any

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import (
    MockProcessServices,
    MockStatsManager,
)
from Plugins.sim.pult_web.plugin import _DRAIN_TIMEOUT_S, PultWebPlugin

_ROUNDS = 150
_BODY = b'{"x": 1}'
_BIG = b"x" * 5000  # больше _MAX_BODY_BYTES (4096) -> 413
_HUGE = b"x" * 600_000  # сотни КБ при отказе: больше прежнего потолка доотдачи 64 КБ, меньше 1 МиБ


class _FakeDeviceHubClient:
    """Двойник ``DeviceHubClient``: команда до него не должна дойти ни в одном отказе."""

    calls: list[tuple[str, dict]] = []

    def __init__(self, ctx: Any, target_process: str = "robot", default_timeout: float = 2.0) -> None:
        pass

    def request(self, command: str, args: dict | None = None, timeout: float | None = None) -> dict:
        _FakeDeviceHubClient.calls.append((command, dict(args or {})))
        return {"status": "ok"}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def port(monkeypatch: pytest.MonkeyPatch):
    _FakeDeviceHubClient.calls.clear()
    monkeypatch.setattr("Plugins.sim.pult_web.plugin.DeviceHubClient", _FakeDeviceHubClient)
    p = _free_port()
    services = MockProcessServices(name="pult", stats_manager=MockStatsManager())
    ctx = PluginContext(
        services=services,
        config={"host": "127.0.0.1", "port": p, "mjpeg_url": "http://127.0.0.1:8091/", "timeout_s": 1.0},
    )
    plugin = PultWebPlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    yield p
    plugin.shutdown(ctx)


def _exchange(
    port: int,
    path: str,
    body: bytes,
    *,
    host: str | None = None,
    ctype: str = "application/json",
    content_length: int | None = None,
) -> int:
    """Отправить POST (заголовки и тело — ДВУМЯ send, как http.client) и вернуть код ответа."""
    length = len(body) if content_length is None else content_length
    head = (
        f"POST {path} HTTP/1.1\r\n"
        f"Host: {host or f'127.0.0.1:{port}'}\r\n"
        f"Content-Type: {ctype}\r\n"
        f"Content-Length: {length}\r\n\r\n"
    ).encode("ascii")
    with socket.create_connection(("127.0.0.1", port), timeout=5.0) as sock:
        sock.sendall(head)
        sock.sendall(body)
        raw = b""
        while b"\r\n" not in raw:
            chunk = sock.recv(4096)
            if not chunk:
                break
            raw += chunk
    assert raw.startswith(b"HTTP/"), f"ответа нет: {raw!r}"
    return int(raw.split(b" ", 2)[1])


#: (метка, путь, тело, kwargs, ожидаемый код) — по одному на каждый ранний отказ.
_FAMILY = [
    ("forbidden_host_403", "/api/truth/reset", _BODY, {"host": "evil.example:80"}, 403),
    ("unsupported_type_415", "/api/run", _BODY, {"ctype": "text/plain"}, 415),
    ("unknown_route_404", "/api/nope", _BODY, {}, 404),
    ("negative_length_400", "/api/run", _BODY, {"content_length": -1}, 400),
    ("too_large_413", "/api/run", _BIG, {}, 413),
    ("negative_length_huge_body_400", "/api/run", _HUGE, {"content_length": -1}, 400),
    ("unsupported_type_huge_body_415", "/api/preset/commit", _HUGE, {"ctype": "text/plain"}, 415),
]


@pytest.mark.parametrize(("label", "path", "body", "kwargs", "expected"), _FAMILY, ids=[f[0] for f in _FAMILY])
def test_early_reject_response_always_arrives(port, label, path, body, kwargs, expected) -> None:
    """Ответ раннего отказа доходит до клиента в каждом из ``_ROUNDS`` обменов."""
    failures: list[str] = []
    for i in range(_ROUNDS):
        try:
            status = _exchange(port, path, body, **kwargs)
        except OSError as exc:
            failures.append(f"#{i}: {type(exc).__name__}: {exc}")
            continue
        if status != expected:
            failures.append(f"#{i}: код {status}, ожидался {expected}")
    assert not failures, f"{label}: {len(failures)} из {_ROUNDS} без ответа; первые: {failures[:3]}"
    assert _FakeDeviceHubClient.calls == [], "отказ не должен доходить до команды"


def test_early_reject_keepalive_client_gets_eof_right_after_response(port) -> None:
    """Клиент с keep-alive (как браузер) читает ответ и сам НЕ закрывает сокет — ждёт EOF.

    Полузакрытие (``shutdown(SHUT_WR)`` в ``_linger_close``) обязано отдать EOF сразу после
    ответа. Без него сервер ждал бы EOF клиента, клиент — сервера, и соединение висело бы до
    ``_DRAIN_TIMEOUT_S`` (2 с) на каждый ранний отказ (инъекция лида 2026-09-29: без
    полузакрытия прочие тесты файла зелёные — свойство сторожит только этот тест)."""
    head = (
        "POST /api/truth/reset HTTP/1.1\r\n"
        "Host: evil.example:80\r\n"
        "Content-Type: application/json\r\n"
        "Connection: keep-alive\r\n"
        f"Content-Length: {len(_BODY)}\r\n\r\n"
    ).encode("ascii")
    with socket.create_connection(("127.0.0.1", port), timeout=5.0) as sock:
        sock.sendall(head)
        sock.sendall(_BODY)
        t0 = time.perf_counter()
        raw = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            raw += chunk
        elapsed = time.perf_counter() - t0
    assert raw.startswith(b"HTTP/1.1 403") or raw.startswith(b"HTTP/1.0 403"), raw[:80]
    assert elapsed < 1.0, f"EOF пришёл через {elapsed:.2f} с после отправки — сервер держал соединение"


def test_early_reject_total_deadline_closes_trickling_client(port) -> None:
    """Общий дедлайн ``_DRAIN_TIMEOUT_S`` не продлевается медленной струйкой байт.

    Клиент получает 403 (чужой Host, ``Content-Length: 1000000``), сам НЕ закрывает сокет
    и шлёт по байту каждые 0.3 с. Сервер обязан закрыть соединение не позже
    ``_DRAIN_TIMEOUT_S`` + запас — это видно на границе ОС: очередной ``send`` клиента падает
    (RST). Инъекция «таймаут на каждый ``recv`` без общего дедлайна» продлевает ожидание
    каждым байтом — ``send`` не падает шесть секунд (замер ревью: 6.01 с против 2.02 с),
    тест краснеет. Клиент — daemon-поток с ``join`` по дедлайну: зависшее не блокирует набор."""
    head = (
        "POST /api/truth/reset HTTP/1.1\r\n"
        "Host: evil.example:80\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: 1000000\r\n\r\n"
    ).encode("ascii")
    observed: dict[str, Any] = {"failed_at": None}
    watch_s = 6.0  # заведомо дольше дедлайна сервера — по нему «не закрыл» отличается от «закрыл»

    def _trickle() -> None:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5.0) as sock:
                sock.sendall(head)
                t0 = time.perf_counter()
                while time.perf_counter() - t0 < watch_s:
                    try:
                        sock.sendall(b"x")
                    except OSError as exc:
                        observed["failed_at"] = time.perf_counter() - t0
                        observed["error"] = type(exc).__name__
                        return
                    time.sleep(0.3)
        except OSError as exc:  # не смогли даже подключиться — это провал, а не «закрыл»
            observed["connect_error"] = repr(exc)

    thread = threading.Thread(target=_trickle, daemon=True)
    thread.start()
    thread.join(timeout=watch_s + 4.0)
    assert not thread.is_alive(), "клиент-струйка завис — join по дедлайну истёк"
    assert "connect_error" not in observed, observed
    failed_at = observed["failed_at"]
    assert failed_at is not None, f"сервер не закрыл соединение за {watch_s} с: дедлайн доотдачи не общий"
    assert failed_at <= _DRAIN_TIMEOUT_S + 1.0, (
        f"сервер закрыл только на {failed_at:.2f} с при дедлайне {_DRAIN_TIMEOUT_S} с"
    )


def test_handler_closes_connection_after_response_http10(port) -> None:
    """Сервер закрывает соединение после ответа даже на keep-alive-запрос (HTTP/1.0).

    ``_linger_close`` опирается на «один запрос на соединение» (флаг ``_body_consumed`` на
    экземпляре, доотдача после цикла ``handle``). Свойство видно на границе ОС: клиент
    HTTP/1.1 с ``Connection: keep-alive`` получает EOF сразу после ответа. При переходе на
    ``protocol_version = "HTTP/1.1"`` соединение осталось бы открытым — ``recv`` упал бы
    по таймауту, а не вернул пустые байты."""
    request = (f"GET /api/status HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: keep-alive\r\n\r\n").encode("ascii")
    with socket.create_connection(("127.0.0.1", port), timeout=1.0) as sock:
        sock.sendall(request)
        raw = b""
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                raw += chunk
        except TimeoutError:
            pytest.fail(f"соединение осталось открытым после ответа (keep-alive?): {raw[:60]!r}")
    assert raw.startswith(b"HTTP/1.0 200"), raw[:60]
