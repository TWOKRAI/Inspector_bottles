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
from typing import Any

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import (
    MockProcessServices,
    MockStatsManager,
)
from Plugins.sim.pult_web.plugin import PultWebPlugin

pytestmark = pytest.mark.timeout(120)

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
