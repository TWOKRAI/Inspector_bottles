# -*- coding: utf-8 -*-
"""Независимая слепая приёмка R-4, сквозная — ``pult_web`` над НАСТОЯЩИМ ``DeviceHubClient``.

Существующие route-тесты подменяют ``DeviceHubClient`` двойником, который отдаёт УЖЕ
нормализованный dict, — поэтому слепы к потере ``code`` внутри клиента. Здесь клиент
настоящий (``PultWebPlugin`` строит его сам), подменён только ``ctx.router_manager``:
его ``request()`` отдаёт конверт, построенный РЕАЛЬНЫМ ``reply_to_request``.

- F. конверт-конфликт (``code=conflict``, ``current_rev=7``, success=False) ->
  ``POST /api/preset/commit`` отвечает HTTP 409, в JSON-теле code "conflict" и current_rev 7.
- G. транспортный отказ ``{"success": False, "error": "timeout"}`` -> HTTP 504.

Харнесс — техника ``test_acceptance_1_2h_preset.py`` (свободный порт, ``PluginContext`` над
``MockProcessServices``), но БЕЗ ``monkeypatch`` класса ``DeviceHubClient``. Тело ответа
читается целиком до закрытия (Windows: ранние отказы, см. ``_linger_close`` в плагине).
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
from Plugins.hub.device_hub.tests.test_reply_envelope_acceptance import _FakeSendRouter
from Plugins.sim.pult_web.plugin import PultWebPlugin

pytestmark = pytest.mark.timeout(30)

_CONFLICT = {"status": "error", "code": "conflict", "message": "rev mismatch", "current_rev": 7}
_COMMIT_BODY = {"preset": {"layers": [{"name": "cap", "offset_px": [0, 0]}]}, "base_rev": 3}


class _StubRouter:
    """``ctx.router_manager``: ``request()`` отдаёт заранее заданный ответ, вызовы записаны."""

    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls: list[dict] = []

    def request(self, msg: dict, timeout: float | None = None) -> dict:
        self.calls.append(msg)
        return self.response


def _reply_envelope(result: Any, success: bool) -> dict:
    envelope = _FakeSendRouter().reply_to_request(
        {"request_id": "req-1", "reply_to": "test-caller"}, result, success=success
    )
    assert envelope is not None, "reply_to_request вернул None — request_msg без адресата?"
    return envelope


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _post_commit(port: int) -> tuple[int, bytes]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/preset/commit",
        data=json.dumps(_COMMIT_BODY).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


@pytest.fixture
def commit_with_router_reply():
    """Фабрика: поднять ``pult_web`` над настоящими клиентами и ``router_manager`` с ответом ``response``."""
    started: list[tuple[PultWebPlugin, PluginContext]] = []

    def _run(response: dict) -> tuple[int, bytes, _StubRouter]:
        port = _free_port()
        router = _StubRouter(response)
        services = MockProcessServices(name="pult", stats_manager=MockStatsManager(), router_manager=router)
        config = {
            "host": "127.0.0.1",
            "port": port,
            "mjpeg_url": "http://127.0.0.1:8091/",
            "robot_process": "robot",
            "timeout_s": 1.0,
        }
        ctx = PluginContext(services=services, config=config)
        plugin = PultWebPlugin()
        plugin.configure(ctx)
        plugin.start(ctx)
        started.append((plugin, ctx))
        status, raw = _post_commit(port)
        return status, raw, router

    yield _run

    for plugin, ctx in started:
        plugin.shutdown(ctx)


def test_f_conflict_reply_becomes_http_409(commit_with_router_reply) -> None:
    """F: конфликт от процесса сцены -> HTTP 409, а не 504."""
    status, raw, router = commit_with_router_reply(_reply_envelope(dict(_CONFLICT), success=False))

    assert router.calls, "команда не дошла до router_manager.request — тест не проверяет клиента"
    assert status == 409, f"ждали 409, получили {status}: {raw[:300]!r}"


def test_f_conflict_body_carries_code(commit_with_router_reply) -> None:
    """F: в теле ответа code == "conflict"."""
    _status, raw, _router = commit_with_router_reply(_reply_envelope(dict(_CONFLICT), success=False))

    assert json.loads(raw.decode("utf-8")).get("code") == "conflict", f"тело: {raw[:300]!r}"


def test_f_conflict_body_carries_current_rev(commit_with_router_reply) -> None:
    """F: в теле ответа current_rev == 7 (фронт по нему перечитывает пресет)."""
    _status, raw, _router = commit_with_router_reply(_reply_envelope(dict(_CONFLICT), success=False))

    assert json.loads(raw.decode("utf-8")).get("current_rev") == 7, f"тело: {raw[:300]!r}"


def test_g_transport_failure_stays_http_504(commit_with_router_reply) -> None:
    """G: «не дошло» (транспортный отказ) по-прежнему 504."""
    status, raw, router = commit_with_router_reply({"success": False, "error": "timeout"})

    assert router.calls, "команда не дошла до router_manager.request — тест не проверяет клиента"
    assert status == 504, f"ждали 504, получили {status}: {raw[:300]!r}"
