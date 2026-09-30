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
    te: str | None = None,
) -> int:
    """Отправить POST (заголовки и тело — ДВУМЯ send, как http.client) и вернуть код ответа."""
    length = len(body) if content_length is None else content_length
    framing = f"Transfer-Encoding: {te}\r\n" if te else f"Content-Length: {length}\r\n"
    head = (
        f"POST {path} HTTP/1.1\r\nHost: {host or f'127.0.0.1:{port}'}\r\nContent-Type: {ctype}\r\n{framing}\r\n"
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
    # Ветка TE в условии «тела нет» `_linger_close` (ревью ит.2, K4): без неё 501 на chunked-теле
    # в сотни КБ терялся в 8-31 % обменов, а маленькие тела и 30 раундов этого не видели.
    ("chunked_huge_body_501", "/api/run", _HUGE, {"te": "chunked"}, 501),
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


def _raw_status(port: int, method: str, path: str, header_lines: list[str], body: bytes) -> int:
    """Запрос с ТОЧНЫМИ заголовками (клиент stdlib не пошлёт chunked без длины, `abc`, дубли).

    Заголовки и тело — двумя ``send``, ответ читается до первой строки."""
    head = (
        f"{method} {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n" + "".join(f"{h}\r\n" for h in header_lines) + "\r\n"
    ).encode("ascii")
    with socket.create_connection(("127.0.0.1", port), timeout=5.0) as sock:
        sock.sendall(head)
        if body:
            sock.sendall(body)
        raw = b""
        while b"\r\n" not in raw:
            chunk = sock.recv(4096)
            if not chunk:
                break
            raw += chunk
    assert raw.startswith(b"HTTP/"), f"ответа нет: {raw!r}"
    return int(raw.split(b" ", 2)[1])


_JSON = "Content-Type: application/json"
_CHUNKED_BODY = b"7\r\n{}      \r\n0\r\n\r\n"

#: (метка, заголовки, тело, ожидаемый код) — кадрирование, которое сервер не может разобрать.
_BAD_FRAMING = [
    ("chunked_no_length_501", [_JSON, "Transfer-Encoding: chunked"], _CHUNKED_BODY, 501),
    ("chunked_with_length_501", [_JSON, "Transfer-Encoding: chunked", "Content-Length: 5"], _CHUNKED_BODY, 501),
    ("unknown_coding_501", [_JSON, "Transfer-Encoding: gzip"], _BODY, 501),
    ("length_abc_400", [_JSON, "Content-Length: abc"], _BODY, 400),
    ("length_plus_sign_400", [_JSON, "Content-Length: +8"], _BODY, 400),
    ("length_empty_400", [_JSON, "Content-Length: "], _BODY, 400),
    ("length_list_conflict_400", [_JSON, "Content-Length: 8, 9"], _BODY, 400),
    ("length_two_headers_conflict_400", [_JSON, "Content-Length: 8", "Content-Length: 9"], _BODY, 400),
    ("length_zero_then_body_400", [_JSON, "Content-Length: 0, 8"], _BODY, 400),
]


@pytest.mark.parametrize(("label", "headers", "body", "expected"), _BAD_FRAMING, ids=[f[0] for f in _BAD_FRAMING])
def test_unparseable_body_framing_rejected_before_command(port, label, headers, body, expected) -> None:
    """Тело, длину которого не понять, отклоняется ДО команды — не выполняется с ``{}``.

    До фикса (ревью pult-flake, 2026-09-29) ``Transfer-Encoding: chunked`` и
    ``Content-Length: abc`` на валидном маршруте давали 200 и ``belt.run`` с пустыми
    аргументами: тело не читалось, но считалось прочитанным. Ответ обязан доходить в каждом
    из обменов (отказ идёт через ``_linger_close`` — тело доотдаётся, RST нет)."""
    for i in range(30):
        status = _raw_status(port, "POST", "/api/run", headers, body)
        assert status == expected, f"{label} #{i}: код {status}, ожидался {expected}"
    assert _FakeDeviceHubClient.calls == [], f"{label}: отказ дошёл до команды: {_FakeDeviceHubClient.calls[:2]}"


def test_duplicate_equal_content_length_is_accepted(port) -> None:
    """Совпадающие значения списком (``Content-Length: 8, 8``) — один заголовок (RFC 9110 §8.6):
    команда выполняется с настоящим телом. Граница «отказ только для противоречия», а не для дубля."""
    status = _raw_status(port, "POST", "/api/run", [_JSON, "Content-Length: 8, 8"], b'{"a": 1}')
    assert status == 200
    assert _FakeDeviceHubClient.calls == [("belt.run", {"a": 1})]


def test_get_without_body_unchanged(port) -> None:
    """GET без тела (путь, не проходящий через ``_read_command_body``) не затронут: 200 и команда ушла."""
    status = _raw_status(port, "GET", "/api/status", [], b"")
    assert status == 200
    assert _FakeDeviceHubClient.calls == [("belt.status", {})]
