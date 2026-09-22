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

Плюс — правки ревью Task 2.3b (итерация 1): состояние ошибки на странице,
jog без лишних стопов/осиротевших таймеров (проверяется НАСТОЯЩИМ ``<script>``
страницы через ``node`` — ``tests/page_offline.mjs``, техника ревьюера, без
headless-браузера), localhost-страж и content-type-страж обработчика, и
пересмотренный ``test_shutdown_does_not_hang`` с реально висящим запросом.
"""

from __future__ import annotations

import http.client
import json
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
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
_PAGE_HARNESS = Path(__file__).with_name("page_offline.mjs")
_NODE = shutil.which("node")


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
        #: ``True`` — belt.status отвечает как отказавший robot (страница должна
        #: показать «robot не отвечает», ревью п.1).
        self.status_error: bool = False
        self._lock = threading.Lock()

    def request(self, command: str, args: dict | None = None, timeout: float | None = None) -> dict:
        if self.sleep_s:
            time.sleep(self.sleep_s)
        args = dict(args or {})
        with self._lock:
            self.calls.append((command, args))
        if command == "belt.status" and self.status_error:
            return {"status": "error", "message": "timeout"}
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
    """``shutdown()`` не ждёт РЕАЛЬНЫЙ запрос в работе, а не только "висящее" соединение.

    Двойник ``robot`` спит 3 с внутри ``client.request()`` (тот самый вызов из
    потока HTTP-обработчика) — дольше любого разумного порога закрытия
    процесса. ``ThreadingHTTPServer.shutdown()`` останавливает только цикл
    ``serve_forever()`` (наш ``_server_thread``), который мы join'им; сам
    обработчик слов запроса — ОТДЕЛЬНЫЙ поток ``ThreadingMixIn``, унаследованный
    ``daemon_threads = True`` (stdlib ``http.server.ThreadingHTTPServer``, не
    переопределён в ``_PultHTTPServer``) — значит на него ``shutdown()``
    ждать не обязан и не ждёт. Порог 2 с — с большим запасом от 3-секундного
    сна двойника; если бы ``shutdown()`` дожидался обработчик, тест поймал бы
    это по времени, а не по догадке.

    Красный при снятии `server.shutdown()` (проверено вручную, см. отчёт) —
    без него `serve_forever()` не узнаёт об остановке и `_server_thread.join`
    жуёт свои 5 с. Красный и при `daemon_threads = False` — тогда сам процесс
    (не этот вызов, а интерпретатор при завершении) ждал бы обработчик; тест
    проверяет наблюдаемое здесь время `shutdown()`, а `daemon_threads`
    проверен отдельно (см. отчёт разработчика — ручная инъекция).
    """
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
            "timeout_s": 10.0,
        },
    )
    plugin = PultWebPlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    assert plugin._state == "running"
    client = plugin._client
    client.sleep_s = 3.0

    slow_result: dict[str, Any] = {}
    slow_done = threading.Event()

    def _slow_request() -> None:
        try:
            status, _raw = _http(port, "POST", "/api/run", {"freq_hz": 10, "reverse": False}, timeout=10.0)
            slow_result["status"] = status
        except Exception as exc:  # noqa: BLE001 - соединение может оборваться сервером, это не провал теста
            slow_result["error"] = repr(exc)
        finally:
            slow_done.set()

    slow_thread = threading.Thread(target=_slow_request, daemon=True)
    slow_thread.start()
    time.sleep(0.3)  # дать медленному запросу занять свой поток обработчика ДО shutdown()

    outcome: dict[str, Any] = {}

    def _shutdown() -> None:
        t0 = time.monotonic()
        plugin.shutdown(ctx)
        outcome["elapsed"] = time.monotonic() - t0

    thread = threading.Thread(target=_shutdown, daemon=True)
    thread.start()
    thread.join(timeout=10.0)

    assert not thread.is_alive(), "plugin.shutdown() не вернулся за 10 с — завис"
    assert outcome.get("elapsed", 999.0) < 2.0, (
        f"shutdown() дождался медленный запрос в работе: {outcome.get('elapsed')} с (порог 2 с)"
    )
    assert plugin._state == "stopped"

    assert slow_done.wait(timeout=10.0), "медленный запрос не завершился сам по себе после shutdown()"


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


# --------------------------------------------------------------------------- #
# 4 — JS страницы (ревью Task 2.3b, п.1-4): реальный <script> через node      #
# --------------------------------------------------------------------------- #


def _run_page_js(port: int, scenario: str) -> dict:
    """Прогнать НАСТОЯЩИЙ ``<script>`` страницы (``page_offline.mjs``) и разобрать stdout."""
    assert _NODE is not None, "node недоступен в PATH — см. отчёт, офлайн-JS-тесты пропущены"
    result = subprocess.run(
        [_NODE, str(_PAGE_HARNESS), str(port), scenario],
        capture_output=True,
        text=True,
        timeout=15.0,
    )
    assert result.returncode == 0, f"page_offline.mjs упал: stdout={result.stdout!r} stderr={result.stderr!r}"
    return json.loads(result.stdout) if result.stdout.strip() else {}


@pytest.mark.skipif(_NODE is None, reason="node недоступен в PATH")
def test_page_jogstop_is_noop_without_active_jog(pult) -> None:
    """Ревью п.2: ``jogStop`` не должен слать ``/api/stop``, если jog не начинался.

    До правки: ``pointerleave`` без предшествующего ``pointerdown`` (наведение
    без нажатия), ``blur`` окна и ``visibilitychange`` вкладки — КАЖДЫЙ звал
    ``post("/api/stop")`` безусловно, даже когда лента могла быть запущена
    кем-то другим (Пуск/прототип/backend_ctl) — случайный стоп чужой ленты.
    """
    _plugin, _ctx, client, port = pult
    n_before = len(client.calls)
    _run_page_js(port, "no_press")
    stop_calls = [c for c in client.calls[n_before:] if c[0] == "belt.stop"]
    assert stop_calls == [], f"jogStop() без активного jog всё равно послал /api/stop: {stop_calls!r}"


@pytest.mark.skipif(_NODE is None, reason="node недоступен в PATH")
def test_page_no_orphan_jog_interval_after_multitouch(pult) -> None:
    """Ревью п.3: второй ``pointerdown`` во время активного jog не должен оставлять сиротский таймер.

    До правки: ``jogTimer`` — одна переменная; второй ``jogStart`` (второй
    палец на другой jog-кнопке) перезаписывал её, не почистив первый
    ``setInterval`` — тот продолжал слать ``/api/jog`` каждые 200 мс НАВСЕГДА,
    даже после того как обе кнопки отпущены (лента не останавливается).

    Орфанный таймер живёт, пока жив node-процесс, — скрипт сам ждёт 1 с
    ПОСЛЕ отпускания обеих кнопок ДО своего ``process.exit``, поэтому все
    тики орфана (если он есть) успевают дойти до ``client.calls`` за время
    работы ``_run_page_js``; проверка ПОСЛЕ завершения подпроцесса ничего не
    поймает — таймер умирает вместе с процессом. Считаем ровно то, что
    накопилось за время сценария: с починкой — второй ``pointerdown`` во
    время активного jog игнорируется (п.3), значит ровно один ``belt.jog``
    (первое нажатие) и ровно один ``belt.stop`` (первое отпускание; второе —
    no-op по п.2).
    """
    _plugin, _ctx, client, port = pult
    n_before = len(client.calls)
    _run_page_js(port, "multitouch")  # скрипт сам ждёт 1 с после отпускания обеих кнопок
    scenario_calls = client.calls[n_before:]
    jog_calls = [c for c in scenario_calls if c[0] == "belt.jog"]
    stop_calls = [c for c in scenario_calls if c[0] == "belt.stop"]
    assert len(jog_calls) == 1, f"ожидали ровно один belt.jog (второй палец игнорируется, п.3): {jog_calls!r}"
    assert len(stop_calls) == 1, f"ожидали ровно один belt.stop (второй pointerup — no-op, п.2): {stop_calls!r}"


@pytest.mark.skipif(_NODE is None, reason="node недоступен в PATH")
def test_page_shows_offline_when_status_errors(pult) -> None:
    """Ревью п.1: ``pollStatus`` должен показывать «robot не отвечает» на отказ, не ``undefined``.

    До правки: проверка ``s.status !== "error"`` — у ответа ``belt.*`` ключа
    ``status`` нет вовсе (см. план, разведка Task 2.3b п.2), значит условие
    было ВСЕГДА истинным и страница печатала ``encoder=undefined`` и т.д.
    даже когда ``robot`` реально отказал (504, ``{ok: false, ...}``).
    """
    _plugin, _ctx, client, port = pult
    client.status_error = True
    try:
        out = _run_page_js(port, "status_error")
    finally:
        client.status_error = False
    assert out.get("statusText") == "robot не отвечает", f"страница напечатала: {out!r}"


# --------------------------------------------------------------------------- #
# 5 — localhost-страж и content-type-страж обработчика (ревью Task 2.3b, п.5) #
# --------------------------------------------------------------------------- #


def _http_with_headers(port: int, method: str, path: str, body: bytes | None, headers: dict) -> tuple[int, bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5.0)
    try:
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def test_foreign_host_header_rejected_403_on_get_and_post(pult) -> None:
    _plugin, _ctx, client, port = pult
    n_before = len(client.calls)

    status_get, raw_get = _http_with_headers(port, "GET", "/", None, {"Host": "rebind.evil.example"})
    assert status_get == 403, f"GET / с чужим Host -> {status_get}, тело: {raw_get[:200]!r}"
    assert json.loads(raw_get) == {"ok": False, "error": "forbidden_host"}

    status_post, raw_post = _http_with_headers(
        port,
        "POST",
        "/api/run",
        b'{"freq_hz": 10}',
        {"Content-Type": "application/json", "Host": "rebind.evil.example"},
    )
    assert status_post == 403, f"POST /api/run с чужим Host -> {status_post}, тело: {raw_post[:200]!r}"
    assert json.loads(raw_post) == {"ok": False, "error": "forbidden_host"}

    assert client.calls[n_before:] == [], "чужой Host не должен доходить до forward'а в robot"


def test_non_json_content_type_rejected_415(pult) -> None:
    _plugin, _ctx, client, port = pult
    n_before = len(client.calls)

    status, raw = _http_with_headers(
        port,
        "POST",
        "/api/run",
        b'{"freq_hz": 50, "reverse": false}',
        {"Content-Type": "text/plain;charset=UTF-8"},
    )
    assert status == 415, f"text/plain POST -> {status}, тело: {raw[:200]!r}"
    assert json.loads(raw) == {"ok": False, "error": "unsupported_media_type"}
    assert client.calls[n_before:] == [], "двойник не должен был получить ни одного вызова при 415"
