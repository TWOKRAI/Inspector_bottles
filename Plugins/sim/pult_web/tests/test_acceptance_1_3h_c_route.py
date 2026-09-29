# -*- coding: utf-8 -*-
"""RED-приёмка Task 1.3h-c, критерий S4 — маршрут `POST /api/preset/sprites` на `pult_web`.

Слепой прогон независимого tester (worktree `ls-13hc-s-tester`, коммит `c8fe3540`, до реализации).
Контракт (план `plans/line-sim-layer-editor/task-1.3h-c-layers.md`): тело `{}` уходит командой
`preset.sprites` клиенту процесса `layers` (`layers_process`, не `camera` и не `robot`), тем же
`DeviceHubClient`, что у `/api/preset/layout`; таймаут — «как у layout» (5.0 с); ответ двойника
проходит как есть; `io_error` -> HTTP 500 (таблица кодов уже есть в плагине).

Двойник `DeviceHubClient` — копия техники `test_acceptance_1_3h_layout_route.py` (не импорт из
чужого теста). Все HTTP-вызовы идут в daemon-потоке с дедлайном join: `pytest-timeout` в проекте
не установлен, маркер `timeout` ничего не делает.
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

_SPRITES_OK = {
    "status": "ok",
    "dir": "data/line_sim",
    "files": [
        {"path": "a.png", "sprite_source": "../../data/line_sim/a.png"},
        {"path": "sub/b.PNG", "sprite_source": "../../data/line_sim/sub/b.PNG"},
    ],
    "truncated": False,
    "layer_template": {"name": "_", "mode": "static", "sprite_source": "_", "scale": 1.0},
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


def _post_sprites(port: int, layers_client: _FakeDeviceHubClient, reply: dict) -> tuple[int, dict]:
    layers_client.raw_responses["preset.sprites"] = reply
    status, raw = _http(port, "POST", "/api/preset/sprites", {})
    try:
        return status, json.loads(raw.decode("utf-8"))
    except ValueError:
        return status, {"_raw": raw[:200].decode("utf-8", "replace")}


def test_s4_route_forwards_empty_body_to_layers_and_passes_reply_as_is(start_pult) -> None:
    port = start_pult()
    layers = _client_for("layers")
    assert layers is not None, "нет клиента с target_process='layers'"

    status, body = _post_sprites(port, layers, dict(_SPRITES_OK))

    assert status == 200, f"POST /api/preset/sprites -> {status}, тело: {body!r} (маршрута нет?)"
    assert body == _SPRITES_OK, f"ответ команды должен пройти как есть: {body!r}"
    sprites_calls = [c for c in layers.calls_with_timeout if c[0] == "preset.sprites"]
    assert len(sprites_calls) == 1, f"ожидался ровно один preset.sprites в layers-клиенте: {layers.calls!r}"
    assert sprites_calls[0][1] == {}, f"тело `{{}}` изменено при форварде: {sprites_calls[0][1]!r}"


def test_s4_route_targets_only_the_layers_client(start_pult) -> None:
    """Ни `camera`/`robot`, ни клиент сцены не получают `preset.sprites`."""
    port = start_pult()
    layers = _client_for("layers")
    assert layers is not None, "нет клиента с target_process='layers'"

    _post_sprites(port, layers, dict(_SPRITES_OK))

    assert [c[0] for c in layers.calls if c[0] == "preset.sprites"] == ["preset.sprites"], layers.calls
    strays = [
        (c.target_process, cmd)
        for c in _FakeDeviceHubClient.instances
        if c is not layers
        for cmd, _ in c.calls
        if cmd == "preset.sprites"
    ]
    assert strays == [], f"preset.sprites попал не только в layers: {strays!r}"


def test_s4_route_timeout_is_like_layout(start_pult) -> None:
    port = start_pult()
    layers = _client_for("layers")
    assert layers is not None, "нет клиента с target_process='layers'"

    _post_sprites(port, layers, dict(_SPRITES_OK))

    sprites_calls = [c for c in layers.calls_with_timeout if c[0] == "preset.sprites"]
    assert len(sprites_calls) == 1, layers.calls
    assert sprites_calls[0][2] == 5.0, (
        f"таймаут маршрута sprites — как у layout (5.0 с), передан {sprites_calls[0][2]!r}"
    )


def test_s4_io_error_is_http_500_with_body_as_is(start_pult) -> None:
    port = start_pult()
    layers = _client_for("layers")
    assert layers is not None, "нет клиента с target_process='layers'"
    io_error = {"status": "error", "code": "io_error", "message": "каталог не найден: data/line_sim"}

    status, body = _post_sprites(port, layers, dict(io_error))

    assert status == 500, f"io_error двойника -> HTTP {status}, тело: {body!r} (ожидалось 500)"
    assert body == io_error, f"тело ошибки должно пройти как есть: {body!r}"


def test_s4_bad_request_is_http_400_with_body_as_is(start_pult) -> None:
    port = start_pult()
    layers = _client_for("layers")
    assert layers is not None, "нет клиента с target_process='layers'"
    bad = {"status": "error", "code": "bad_request", "message": "sprites_dir вне ограды"}

    status, body = _post_sprites(port, layers, dict(bad))

    assert status == 400 and body == bad, f"bad_request двойника -> HTTP {status}, тело {body!r}"
