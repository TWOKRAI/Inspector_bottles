# -*- coding: utf-8 -*-
"""RED-приёмка Task 5.1b — §3 контракта, сторона пульта: отданная HTML-страница не
должна содержать сегмент «те же X/Y с новым энкодером» (причина, отменённая 5.1b).

Независимый tester, worktree на коммите контракта лида (602be8ec, до реализации).
Контракт — ТОЛЬКО ``plans/line-sim/phase-5-contract-5.1b.md`` §3. Сегодня
``_PAGE_TEMPLATE`` (``Plugins/sim/pult_web/plugin.py``) буквально содержит строку
`" · те же X/Y с новым энкодером " + c.repeats_frozen_xy +` внутри JS-функции
``pollJournal`` — ожидаемый провал ``AssertionError`` (сегмент найден там, где
контракт требует отсутствия).

Харнесс скопирован с ``Plugins/sim/pult_web/tests/test_pult_journal_routes.py``
(шов подмены ``DeviceHubClient`` по имени в модуле плагина, свободный порт, реальный
HTTP GET "/" через ``urllib``).
"""

from __future__ import annotations

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
_FROZEN_XY_SEGMENT = "те же X/Y с новым энкодером"


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


def _http_get(port: int, path: str) -> tuple[int, bytes]:
    url = f"http://127.0.0.1:{port}{path}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


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
    try:
        yield plugin, ctx, services, port
    finally:
        plugin.shutdown(ctx)


def test_page_has_no_frozen_segment(pult) -> None:
    """§3 контракта 5.1b: отменённая причина не должна упоминаться на отданной
    странице пульта, независимо от того, что говорит ``sim_robot.journal``."""
    _plugin, _ctx, _services, port = pult

    status, raw = _http_get(port, "/")
    assert status == 200, f"GET / -> {status}, тело: {raw[:300]!r}"
    body = raw.decode("utf-8")
    assert _FROZEN_XY_SEGMENT not in body, (
        f"§3 контракта 5.1b: сегмент {_FROZEN_XY_SEGMENT!r} должен исчезнуть со страницы пульта"
    )
    assert "repeats_frozen_xy" not in body, (
        "§3 контракта 5.1b: ссылка на c.repeats_frozen_xy не должна остаться в JS-шаблоне страницы"
    )
