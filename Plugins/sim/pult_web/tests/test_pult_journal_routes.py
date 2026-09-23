# -*- coding: utf-8 -*-
"""RED-приёмка Task 5.1 — маршруты журнала заданий в веб-пульте.

Независимый tester, worktree на коммите контракта лида (до реализации). Контракт —
ТОЛЬКО «Контракт лида 5.1 (ред. 3, 2026-09-23, до тестера)», §3, в
``plans/line-sim/phase-5-ground-truth.md``: ``GET /api/journal`` форвардит команду
``sim_robot.journal``, ``POST /api/journal/reset`` — ``sim_robot.journal_reset``,
ОБА через тот же тракт ``client.request(...)``, что и ``/api/status`` (см.
``do_GET``/``_dispatch`` в ``Plugins/sim/pult_web/plugin.py``), результат отдаётся
клиенту как JSON КАК ЕСТЬ. Сегодня ``do_GET`` знает только ``"/"``/``"/api/status"``,
``_COMMAND_BY_PATH`` не содержит ``/api/journal/reset`` — оба маршрута отвечают 404
ДО обращения к ``robot`` — ожидаемый провал ``AssertionError`` (404 != 200).

Харнесс скопирован с ``Plugins/sim/pult_web/tests/test_pult_web.py`` (шов подмены
``DeviceHubClient`` по имени в модуле плагина — тест того же файла уже подтверждает
этот шов существующим ЗЕЛЁНЫМ ``test_run_forwards_same_command``, не догадка
тестера).
"""

from __future__ import annotations

import json
import socket
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
_TIMEOUT_S = 1.0


class _FakeDeviceHubClient:
    """Повторяет сигнатуру конструктора ``DeviceHubClient`` (см. ``test_pult_web.py``)."""

    instances: list["_FakeDeviceHubClient"] = []

    def __init__(self, ctx: Any, target_process: str = "robot", default_timeout: float = 2.0) -> None:
        self.ctx = ctx
        self.target_process = target_process
        self.default_timeout = default_timeout
        self.calls: list[tuple[str, dict]] = []
        self.responses: dict[str, dict] = {}
        _FakeDeviceHubClient.instances.append(self)

    def request(self, command: str, args: dict | None = None, timeout: float | None = None) -> dict:
        args = dict(args or {})
        self.calls.append((command, args))
        return dict(self.responses.get(command, {"status": "ok", "echo": args}))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _http(port: int, method: str, path: str, body: Any = None) -> tuple[int, bytes, dict]:
    url = f"http://127.0.0.1:{port}{path}"
    data = None
    headers = {}
    if body is not None:
        data = body if isinstance(body, (bytes, bytearray)) else json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            return resp.status, resp.read(), dict(resp.headers.items())
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers.items()) if exc.headers else {}


@pytest.fixture
def pult(monkeypatch: pytest.MonkeyPatch):
    """Плагин на свободном порту + записывающий двойник ``robot`` (см. ``test_pult_web.py``)."""
    _FakeDeviceHubClient.instances.clear()
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
            "timeout_s": _TIMEOUT_S,
        },
    )
    plugin = PultWebPlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    assert _FakeDeviceHubClient.instances, "плагин не создал DeviceHubClient через ожидаемый шов"
    # С 5.3a плагин строит второго клиента (процесс сцены) — берём клиента robot по адресату.
    client = next(c for c in _FakeDeviceHubClient.instances if c.target_process == "robot")
    try:
        yield plugin, ctx, services, client, port
    finally:
        plugin.shutdown(ctx)


# --------------------------------------------------------------------------- #
# R9 — GET /api/journal форвардит sim_robot.journal, тело — ответ как есть    #
# --------------------------------------------------------------------------- #


def test_get_api_journal_forwards_sim_robot_journal(pult) -> None:
    _plugin, _ctx, _services, client, port = pult
    # Переписано 5.1b: ключ repeats_frozen_xy ушёл из SimJournal.counters() (пульт
    # форвардит тело как есть — сама эта фикстура не проверяет счётную логику
    # журнала, но держим её в форме, которую реально может отдать robot).
    fake_response = {
        "status": "ok",
        "counters": {
            "jobs": 3,
            "dups": 1,
            "done": 2,
            "reads": 40,
            "dups_same_capture": 1,
            "dups_tracked": 0,
        },
        "recent": [],
    }
    client.responses["sim_robot.journal"] = fake_response

    status, raw, _headers = _http(port, "GET", "/api/journal")

    assert client.calls == [("sim_robot.journal", {})], (
        f"двойник получил не ровно один sim_robot.journal с пустым телом: {client.calls!r}"
    )
    assert status == 200, f"GET /api/journal -> {status}, тело: {raw[:300]!r}"
    body = json.loads(raw.decode("utf-8"))
    assert body == fake_response, f"тело ответа не равно ответу двойника как есть: {body!r}"


# --------------------------------------------------------------------------- #
# R10 — POST /api/journal/reset форвардит sim_robot.journal_reset             #
# --------------------------------------------------------------------------- #


def test_post_api_journal_reset_forwards_reset(pult) -> None:
    _plugin, _ctx, _services, client, port = pult
    client.responses["sim_robot.journal_reset"] = {"status": "ok"}

    status, raw, _headers = _http(port, "POST", "/api/journal/reset", {})

    assert client.calls == [("sim_robot.journal_reset", {})], (
        f"двойник получил не ровно один sim_robot.journal_reset с пустым телом: {client.calls!r}"
    )
    assert status == 200, f"POST /api/journal/reset -> {status}, тело: {raw[:300]!r}"
    body = json.loads(raw.decode("utf-8"))
    assert body == {"status": "ok"}, f"тело ответа не равно ответу двойника как есть: {body!r}"
