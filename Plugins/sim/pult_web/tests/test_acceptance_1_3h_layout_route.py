# -*- coding: utf-8 -*-
"""RED-приёмка Task 1.3h-a, критерий I — маршрут `POST /api/preset/layout` на `pult_web`.

Слепой прогон независимого tester (worktree `ls-13h-tester`, коммит `807e4faf`, до реализации).
Контракт (DESIGN лида): тело форвардится КАК ЕСТЬ командой `preset.layout` в `layers_process`
тем же третьим `DeviceHubClient` (`target_process='layers'`), что у `/api/preset/preview`;
таймаут маршрута 5.0 с; код ошибки -> HTTP-статус ровно как у существующих `/api/preset/*`
(`invalid`/`bad_request` -> 400; отказ транспорта без `code` -> 504 `{ok: false, error: ...}`).

Двойник `DeviceHubClient` — копия техники `test_acceptance_1_2h_preset.py` (не импорт из чужого теста).
Все HTTP-вызовы идут в daemon-потоке с дедлайном join: `pytest-timeout` в проекте не установлен,
маркер `timeout` ничего не делает.
"""

from __future__ import annotations

import json
import socket
import threading
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

_MJPEG_URL = "http://127.0.0.1:8091/"
_HTTP_DEADLINE_S = 15.0

#: Тело запроса: небольшое (< общего потолка 4096 байт — потолок маршрута layout контрактом не задан).
_BODY = {
    "preset": {"catalog_dir": "cat", "layers": [{"name": "disk", "mode": "static", "sprite_source": "disk.png"}]},
    "seed": 7,
}
_LAYOUT_OK = {
    "status": "ok",
    "class_name": "A",
    "canvas_px": [64, 64],
    "layers": [{"name": "disk", "png_b64": "AAAA", "center_px": [0, 0], "size_px": [60, 60]}],
}


class _FakeDeviceHubClient:
    """Двойник `DeviceHubClient`: пишет вызовы и переданный `timeout`, отвечает заданным ответом."""

    instances: list["_FakeDeviceHubClient"] = []

    def __init__(self, ctx: Any, target_process: str = "robot", default_timeout: float = 2.0) -> None:
        self.ctx = ctx
        self.target_process = target_process
        self.default_timeout = default_timeout
        self.calls: list[tuple[str, dict]] = []
        self.calls_with_timeout: list[tuple[str, dict, float | None]] = []
        self.raw_responses: dict[str, Any] = {}
        _FakeDeviceHubClient.instances.append(self)

    def request(self, command: str, args: dict | None = None, timeout: float | None = None) -> dict:
        args = dict(args or {})
        self.calls.append((command, args))
        self.calls_with_timeout.append((command, args, timeout))
        if command in self.raw_responses:
            return self.raw_responses[command]
        return {"status": "ok", "echo": args}


def _client_for(target_process: str) -> "_FakeDeviceHubClient | None":
    matches = [c for c in _FakeDeviceHubClient.instances if c.target_process == target_process]
    return matches[-1] if matches else None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _http_once(port: int, method: str, path: str, body: Any) -> tuple[int, bytes]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _http(port: int, method: str, path: str, body: Any) -> tuple[int, bytes]:
    """`_http_once` в daemon-потоке с дедлайном: зависание -> падение теста, а не подвисший прогон."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["result"] = _http_once(port, method, path, body)
        except BaseException as exc:  # noqa: BLE001 — пробросим в основной поток
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(_HTTP_DEADLINE_S)
    assert not thread.is_alive(), f"{method} {path}: нет ответа за {_HTTP_DEADLINE_S} с (зависание)"
    if "error" in box:
        raise box["error"]
    return box["result"]


@pytest.fixture
def start_pult(monkeypatch: pytest.MonkeyPatch):
    """Плагин на свободном порту с фейковым `DeviceHubClient`."""
    _FakeDeviceHubClient.instances.clear()
    monkeypatch.setattr("Plugins.sim.pult_web.plugin.DeviceHubClient", _FakeDeviceHubClient)
    started: list[tuple[PultWebPlugin, PluginContext]] = []

    def _start() -> int:
        port = _free_port()
        services = MockProcessServices(name="pult", stats_manager=MockStatsManager())
        config = {
            "host": "127.0.0.1",
            "port": port,
            "mjpeg_url": _MJPEG_URL,
            "robot_process": "robot",
            "timeout_s": 1.0,
        }
        ctx = PluginContext(services=services, config=config)
        plugin = PultWebPlugin()
        plugin.configure(ctx)
        plugin.start(ctx)
        started.append((plugin, ctx))
        return port

    yield _start

    for plugin, ctx in started:
        plugin.shutdown(ctx)


def _post(port: int, path: str, layers_client: _FakeDeviceHubClient, command: str, reply: dict) -> tuple[int, dict]:
    layers_client.raw_responses[command] = reply
    status, raw = _http(port, "POST", path, _BODY)
    try:
        return status, json.loads(raw.decode("utf-8"))
    except ValueError:
        return status, {"_raw": raw[:200].decode("utf-8", "replace")}


def test_i_route_forwards_and_maps_codes(start_pult) -> None:
    port = start_pult()
    layers = _client_for("layers")
    assert layers is not None, "нет клиента с target_process='layers'"

    # 1. ok: тело форвардится как есть командой preset.layout, ответ команды проходит как есть.
    status, body = _post(port, "/api/preset/layout", layers, "preset.layout", dict(_LAYOUT_OK))
    assert status == 200, f"POST /api/preset/layout -> {status}, тело: {body!r} (маршрута нет?)"
    assert body == _LAYOUT_OK, f"ответ команды должен пройти как есть: {body!r}"
    layout_calls = [c for c in layers.calls_with_timeout if c[0] == "preset.layout"]
    assert len(layout_calls) == 1, f"ожидался ровно один preset.layout в layers-клиенте: {layers.calls!r}"
    assert layout_calls[0][1] == _BODY, f"тело изменено при форварде: {layout_calls[0][1]!r}"
    assert layout_calls[0][2] == 5.0, f"таймаут маршрута layout должен быть 5.0 с, передан {layout_calls[0][2]!r}"
    for other in ("camera", "robot"):
        other_client = _client_for(other)
        other_calls = [c for c in (other_client.calls if other_client else []) if c[0] == "preset.layout"]
        assert other_calls == [], f"preset.layout попал не в layers, а в {other}: {other_calls!r}"

    # 2. invalid -> тот же HTTP-статус, что у /api/preset/preview (контроль: 400), тело как есть.
    invalid = {"status": "error", "code": "invalid", "message": "boom"}
    preview_status, _ = _post(port, "/api/preset/preview", layers, "preset.preview", dict(invalid))
    assert preview_status == 400, f"контроль: preview invalid -> {preview_status} (ожидалось 400)"
    status, body = _post(port, "/api/preset/layout", layers, "preset.layout", dict(invalid))
    assert status == preview_status == 400, f"layout invalid -> HTTP {status}, у preview {preview_status}"
    assert body == invalid, f"тело ошибки должно пройти как есть: {body!r}"

    # 3. bad_request -> 400 (как у preview).
    bad = {"status": "error", "code": "bad_request", "message": "nope"}
    status, body = _post(port, "/api/preset/layout", layers, "preset.layout", dict(bad))
    assert status == 400 and body == bad, f"layout bad_request -> HTTP {status}, тело {body!r}"

    # 4. Отказ транспорта (ответ без code) -> то же видимое поведение, что у preview: 504 {ok: false, error}.
    timeout_reply = {"status": "error", "message": "timeout"}
    preview_status, preview_body = _post(port, "/api/preset/preview", layers, "preset.preview", dict(timeout_reply))
    assert preview_status == 504 and preview_body == {"ok": False, "error": "timeout"}, (
        f"контроль: preview при отказе транспорта -> {preview_status} {preview_body!r}"
    )
    status, body = _post(port, "/api/preset/layout", layers, "preset.layout", dict(timeout_reply))
    assert (status, body) == (preview_status, preview_body), (
        f"layout при отказе транспорта -> {status} {body!r}, у preview {preview_status} {preview_body!r}"
    )
