# -*- coding: utf-8 -*-
"""Hazard-тесты автора для ``PultWebPlugin`` (Task 2.3b плана ``line-sim``).

Три свойства из плана (раздел «Hazard-тесты автора» Task 2.3b):

1. 20 конкурентных ``POST /api/jog`` — каждый доходит двойнику РОВНО один раз
   (``ThreadingHTTPServer`` — поток на соединение, форвард не разделяет
   состояния между запросами, гонки формировать нечему; тест это проверяет
   массово, а не полагается на рассуждение).
2. ``shutdown()`` не виснет, даже если у ``robot`` двойник спит дольше
   таймаута обработчика (форма — вызов в daemon-потоке с join-дедлайном,
   как того требует правило проекта про тесты, которые могут зависнуть).
3. Медленный ``robot`` (двойник спит 2 с при ``timeout_s=1.0``) не блокирует
   ``GET /`` соседнего клиента — ``ThreadingHTTPServer`` даёт каждому
   соединению свой поток.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from typing import Any

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import (
    MockProcessServices,
    MockStatsManager,
)
from Plugins.sim.pult_web.plugin import PultWebPlugin

pytestmark = pytest.mark.timeout(30)

_MJPEG_URL = "http://127.0.0.1:8091/"


class _FakeDeviceHubClient:
    """Двойник ``DeviceHubClient`` — та же форма, что у теста тестера.

    ``sleep_s`` позволяет сымитировать медленный ``robot`` (свойство 3).
    ``calls`` растёт из разных потоков параллельно — ``list.append`` атомарен
    под GIL, но сам список нужен именно как СЧЁТЧИК ФОРВАРДОВ, а не факт
    вызова: свойство 1 требует РОВНО одного вызова на запрос, не "хотя бы".
    """

    def __init__(self, ctx: Any, target_process: str = "robot", default_timeout: float = 2.0) -> None:
        self.ctx = ctx
        self.target_process = target_process
        self.default_timeout = default_timeout
        self.calls: list[tuple[str, dict]] = []
        self.sleep_s: float = 0.0
        self._lock = threading.Lock()

    def request(self, command: str, args: dict | None = None, timeout: float | None = None) -> dict:
        if self.sleep_s:
            time.sleep(self.sleep_s)
        args = dict(args or {})
        with self._lock:
            self.calls.append((command, args))
        return {"status": "ok", "echo": args}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _http(port: int, method: str, path: str, body: Any = None, timeout: float = 10.0) -> tuple[int, bytes]:
    url = f"http://127.0.0.1:{port}{path}"
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


@pytest.fixture
def pult(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("Plugins.sim.pult_web.plugin.DeviceHubClient", _FakeDeviceHubClient)

    port = _free_port()
    stats = MockStatsManager()
    services = MockProcessServices(name="pult", stats_manager=stats)
    ctx = PluginContext(
        services=services,
        config={
            "host": "127.0.0.1",
            "port": port,
            "mjpeg_url": _MJPEG_URL,
            "robot_process": "robot",
            "timeout_s": 1.0,
        },
    )
    plugin = PultWebPlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    client = plugin._client
    try:
        yield plugin, ctx, client, port
    finally:
        plugin.shutdown(ctx)


# --------------------------------------------------------------------------- #
# 1 — 20 конкурентных POST /api/jog: каждый форвардится РОВНО один раз        #
# --------------------------------------------------------------------------- #


def test_concurrent_jog_forwards_each_exactly_once(pult) -> None:
    _plugin, _ctx, client, port = pult
    n = 20
    results: list[int] = [-1] * n

    def _do(i: int) -> None:
        status, _raw = _http(port, "POST", "/api/jog", {"direction": 1, "seq": i})
        results[i] = status

    threads = [threading.Thread(target=_do, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15.0)
        assert not t.is_alive(), "поток jog-запроса не завершился за 15 с (подозрение на зависание)"

    assert all(s == 200 for s in results), f"не все запросы вернули 200: {results!r}"
    assert len(client.calls) == n, f"ожидали ровно {n} форвардов, получили {len(client.calls)}: {client.calls!r}"
    seqs = sorted(args["seq"] for _cmd, args in client.calls)
    assert seqs == list(range(n)), f"часть запросов форвардилась не один раз или потерялась: {seqs!r}"
    assert all(cmd == "belt.jog" for cmd, _args in client.calls)


# --------------------------------------------------------------------------- #
# 2 — shutdown() не виснет при живом сервере, вызов в daemon-потоке с join    #
# --------------------------------------------------------------------------- #


def test_shutdown_does_not_hang(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("Plugins.sim.pult_web.plugin.DeviceHubClient", _FakeDeviceHubClient)

    port = _free_port()
    stats = MockStatsManager()
    services = MockProcessServices(name="pult", stats_manager=stats)
    ctx = PluginContext(
        services=services,
        config={"host": "127.0.0.1", "port": port, "mjpeg_url": _MJPEG_URL, "robot_process": "robot", "timeout_s": 1.0},
    )
    plugin = PultWebPlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    assert plugin._state == "running"

    # Открыть соединение и оставить его "висящим" клиентом, как долго
    # держащаяся вкладка браузера на "GET /" — shutdown() не обязан её
    # закрывать (то же известное ограничение, что у mjpeg_sink), но обязан
    # ОСТАНОВИТЬСЯ САМ за разумное время.
    sock = socket.create_connection(("127.0.0.1", port), timeout=5.0)
    sock.sendall(b"GET / HTTP/1.0\r\n\r\n")

    outcome: dict[str, Any] = {}

    def _shutdown() -> None:
        t0 = time.monotonic()
        plugin.shutdown(ctx)
        outcome["elapsed"] = time.monotonic() - t0

    thread = threading.Thread(target=_shutdown, daemon=True)
    thread.start()
    thread.join(timeout=10.0)

    sock.close()

    assert not thread.is_alive(), "plugin.shutdown() не вернулся за 10 с — завис"
    assert outcome.get("elapsed", 999.0) < 10.0
    assert plugin._state == "stopped"


# --------------------------------------------------------------------------- #
# 3 — медленный robot не блокирует GET / соседнего клиента                    #
# --------------------------------------------------------------------------- #


def test_slow_robot_does_not_block_other_client_get_index(pult) -> None:
    _plugin, _ctx, client, port = pult
    client.sleep_s = 2.0  # дольше timeout_s=1.0 конфига пульта

    slow_result: dict[str, Any] = {}

    def _slow_call() -> None:
        t0 = time.monotonic()
        status, _raw = _http(port, "POST", "/api/run", {"freq_hz": 10, "reverse": False}, timeout=10.0)
        slow_result["status"] = status
        slow_result["elapsed"] = time.monotonic() - t0

    slow_thread = threading.Thread(target=_slow_call, daemon=True)
    slow_thread.start()
    time.sleep(0.2)  # дать медленному запросу занять свой поток

    t0 = time.monotonic()
    status_get, _raw_get = _http(port, "GET", "/", timeout=5.0)
    elapsed_get = time.monotonic() - t0

    assert status_get == 200, f"GET / соседнего клиента отказал: {status_get}"
    assert elapsed_get < 1.0, f"GET / ждал медленного robot ({elapsed_get:.2f} с) — сервер не многопоточен"

    slow_thread.join(timeout=10.0)
    assert not slow_thread.is_alive(), "медленный запрос не завершился за 10 с"
    assert slow_result.get("status") == 200
    assert slow_result.get("elapsed", 0.0) >= 2.0
