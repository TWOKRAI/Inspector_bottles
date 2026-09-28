# -*- coding: utf-8 -*-
"""Hazard-тесты автора — Task 1.2h (маршруты ``/api/preset*`` на ``pult_web``).

Независимая приёмка (``test_acceptance_1_2h_preset.py``) закрывает контракт
(3 маршрута, коды ошибок, потолки тела/таймауты, разметка редактора). Эти
тесты — про опасные места именно этого МЕХАНИЗМА, которые контракт не called
буквально: неизвестный ``code`` в таблице маппинга, отсутствие ``code`` на
маршруте пресета (а не только на ``belt.*``), точная граница потолка тела
(``length == max_bytes`` — не более, off-by-one), утечка настроенного имени
процесса (``layers_process``/``scene_process``) сквозь таблицу маршрутов
вместо хардкода строкового литерала, и то, что таймаут МАРШРУТА не приезжает
случайно на СТАРЫЕ команды (регрессия сигнатуры ``_dispatch``/``do_POST``).

Своя копия харнесса (``_FakeDeviceHubClient``, ``start_pult``, ``_http``) —
та же техника, что в ``test_acceptance_1_2h_preset.py`` и ``test_acceptance_
5_3a.py``; импорт между тестовыми модулями избыточен (тот же довод, что в
докстринге приёмки).
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

_MJPEG_URL = "http://127.0.0.1:8091/"
_TIMEOUT_S = 1.0
_COMMIT_CAP = 262144  # Находка 1 Task 1.2h — потолок тела /api/preset/commit.


class _FakeDeviceHubClient:
    """Двойник по имени конструктора ``DeviceHubClient`` (та же форма, что в приёмке)."""

    instances: list["_FakeDeviceHubClient"] = []

    def __init__(self, ctx: Any, target_process: str = "robot", default_timeout: float = 2.0) -> None:
        self.ctx = ctx
        self.target_process = target_process
        self.default_timeout = default_timeout
        self.calls: list[tuple[str, dict]] = []
        self.calls_with_timeout: list[tuple[str, dict, float | None]] = []
        self.responses: dict[str, dict] = {}
        self.raw_responses: dict[str, Any] = {}
        _FakeDeviceHubClient.instances.append(self)

    def request(self, command: str, args: dict | None = None, timeout: float | None = None) -> dict:
        args = dict(args or {})
        self.calls.append((command, args))
        self.calls_with_timeout.append((command, args, timeout))
        if command in self.raw_responses:
            return self.raw_responses[command]
        return dict(self.responses.get(command, {"status": "ok", "echo": args}))


def _client_for(target_process: str) -> "_FakeDeviceHubClient | None":
    matches = [c for c in _FakeDeviceHubClient.instances if c.target_process == target_process]
    return matches[-1] if matches else None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _http(port: int, method: str, path: str, body: Any = None) -> tuple[int, bytes]:
    url = f"http://127.0.0.1:{port}{path}"
    data = None
    headers = {}
    if body is not None:
        data = body if isinstance(body, (bytes, bytearray)) else json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


@pytest.fixture
def start_pult(monkeypatch: pytest.MonkeyPatch):
    _FakeDeviceHubClient.instances.clear()
    monkeypatch.setattr("Plugins.sim.pult_web.plugin.DeviceHubClient", _FakeDeviceHubClient)
    started: list[tuple[PultWebPlugin, PluginContext]] = []

    def _start(**config_overrides: Any) -> tuple[PultWebPlugin, PluginContext, int]:
        port = _free_port()
        stats = MockStatsManager()
        services = MockProcessServices(name="pult", stats_manager=stats)
        config = {
            "host": "127.0.0.1",
            "port": port,
            "mjpeg_url": _MJPEG_URL,
            "robot_process": "robot",
            "timeout_s": _TIMEOUT_S,
        }
        config.update(config_overrides)
        ctx = PluginContext(services=services, config=config)
        plugin = PultWebPlugin()
        plugin.configure(ctx)
        plugin.start(ctx)
        started.append((plugin, ctx))
        return plugin, ctx, port

    yield _start

    for plugin, ctx in started:
        plugin.shutdown(ctx)


# --------------------------------------------------------------------------- #
# 1. Код вне _ERROR_CODE_TO_HTTP -> 400 (не только три перечисленных в H3)     #
# --------------------------------------------------------------------------- #


def test_unknown_error_code_defaults_to_400(start_pult) -> None:
    """DESIGN: «неизвестный код -> 400». Ломается, если маппинг перепутан на KeyError
    (500 от необработанного исключения) или на молчаливый 504 (старая ветка)."""
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None
    reply = {"status": "error", "code": "quota_exceeded", "message": "boom"}
    scene_client.raw_responses["preset.commit"] = reply

    status, raw = _http(port, "POST", "/api/preset/commit", {"base_rev": "r", "preset": {}})

    assert status == 400, f"неизвестный code -> {status}, тело: {raw[:300]!r}"
    assert json.loads(raw.decode("utf-8")) == reply


# --------------------------------------------------------------------------- #
# 2. preset.commit БЕЗ code в ошибке -> старый 504 (не только belt.*, H4)      #
# --------------------------------------------------------------------------- #


def test_preset_route_error_without_code_still_504(start_pult) -> None:
    """Находка 2 различает по наличию ``code``, а не по имени маршрута — эта
    ветка ломается, если кто-то захардкодит «все preset.* маршруты типизированы»
    вместо честной проверки ``result.get("code")``."""
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None
    scene_client.responses["preset.commit"] = {"status": "error", "message": "нет ответа от процесса"}

    status, raw = _http(port, "POST", "/api/preset/commit", {"base_rev": "r", "preset": {}})

    assert status == 504, f"отказ preset.commit без code -> {status}, тело: {raw[:300]!r}"
    assert json.loads(raw.decode("utf-8")) == {"ok": False, "error": "нет ответа от процесса"}


# --------------------------------------------------------------------------- #
# 3. Граница потолка тела маршрута: ровно max_bytes -> принято, +1 -> 413      #
# --------------------------------------------------------------------------- #


def test_commit_body_exactly_at_cap_is_accepted_one_byte_over_is_not(start_pult) -> None:
    """``length > max_bytes`` (строго больше) — off-by-one здесь резал бы ровно
    граничные тела маршрута ``commit`` (реальные пресеты с диапазонами близки
    к границе на бутылочных объектах, README плана)."""
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None
    scene_client.responses["preset.commit"] = {"status": "ok", "rev": "r2"}

    def _body_of_size(total: int) -> bytes:
        # {"base_rev":"r","preset":{"pad":"..."}}, длина ровно `total` байт.
        prefix = b'{"base_rev":"r","preset":{"pad":"'
        suffix = b'"}}'
        pad_len = total - len(prefix) - len(suffix)
        assert pad_len > 0
        return prefix + b"x" * pad_len + suffix

    exact = _body_of_size(_COMMIT_CAP)
    assert len(exact) == _COMMIT_CAP
    status_exact, raw_exact = _http(port, "POST", "/api/preset/commit", exact)
    assert status_exact == 200, f"тело ровно {_COMMIT_CAP} байт -> {status_exact}, тело: {raw_exact[:300]!r}"

    over = _body_of_size(_COMMIT_CAP + 1)
    assert len(over) == _COMMIT_CAP + 1
    status_over, raw_over = _http(port, "POST", "/api/preset/commit", over)
    assert status_over == 413, f"тело {_COMMIT_CAP + 1} байт -> {status_over}, тело: {raw_over[:300]!r}"


# --------------------------------------------------------------------------- #
# 4. layers_process сконфигурирован, а не захардкожен как "layers" в таблице  #
# --------------------------------------------------------------------------- #


def test_preview_uses_configured_layers_process_name(start_pult) -> None:
    """``_PRESET_ROUTES`` хранит имя АТРИБУТА клиента (``_layers_client``), а не
    строку процесса — ломается, если бы preview был завязан на литерал "layers"
    вместо сконфигурированного ``layers_process``."""
    _plugin, _ctx, port = start_pult(layers_process="gpu_layers")
    custom_client = _client_for("gpu_layers")
    assert custom_client is not None, "клиент с переименованным layers_process не создан"
    custom_client.responses["preset.preview"] = {"status": "ok", "png_b64": "AAAA"}

    status, raw = _http(port, "POST", "/api/preset/preview", {"seeds": [1]})

    assert status == 200, f"preview с переименованным layers_process -> {status}, тело: {raw[:300]!r}"
    assert custom_client.calls == [("preset.preview", {"seeds": [1]})]
    default_layers_client = _client_for("layers")
    assert default_layers_client is None, (
        "клиент 'layers' по умолчанию не должен был завестись при layers_process='gpu_layers'"
    )


# --------------------------------------------------------------------------- #
# 5. Маршрутный таймаут не просачивается на прежние маршруты (regression)     #
# --------------------------------------------------------------------------- #


def test_old_routes_keep_using_pult_timeout_s_not_none_or_preview_timeout(start_pult) -> None:
    """Сигнатура ``_dispatch``/``do_POST`` получила параметр ``timeout`` ради
    preview (5.0 с) — регрессия: если дефолт трактуется неверно, старые
    маршруты либо получат ``timeout=None`` (упадёт в ``client.request``, если
    он не терпит ``None``... двойник терпит, но живой ``DeviceHubClient`` — по
    факту его контракта, не проверено здесь), либо получат чужие 5.0 с."""
    _plugin, _ctx, port = start_pult(timeout_s=2.5)
    scene_client = _client_for("camera")
    assert scene_client is not None
    scene_client.responses["scene.pause"] = {"status": "ok"}

    status, _raw = _http(port, "POST", "/api/scene/pause", {"paused": True})
    assert status == 200

    calls = [c for c in scene_client.calls_with_timeout if c[0] == "scene.pause"]
    assert calls, "scene.pause не дошёл до двойника"
    assert calls[-1][2] == 2.5, f"старый маршрут должен получить общий pult._timeout_s (2.5), получил {calls[-1][2]!r}"


# --------------------------------------------------------------------------- #
# 6. Content-Type-страж всё ещё действует на новых маршрутах пресета          #
# --------------------------------------------------------------------------- #


def test_preset_commit_content_type_guard_still_applies(start_pult) -> None:
    """Гейт ``Content-Type: application/json`` — общий код ``do_POST`` ДО поиска
    в ``_PRESET_ROUTES``; ломается, если бы поиск по новой таблице был вставлен
    раньше проверки типа и обошёл её."""
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None

    url = f"http://127.0.0.1:{port}/api/preset/commit"
    req = urllib.request.Request(url, data=b'{"base_rev":"r","preset":{}}', method="POST")
    # Без заголовка Content-Type вовсе — как голый curl -X POST (докстринг README).
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()

    assert status == 415, f"commit без Content-Type -> {status}, тело: {raw[:300]!r}"
    assert json.loads(raw.decode("utf-8")) == {"ok": False, "error": "unsupported_media_type"}
    assert scene_client.calls == [], "команда не должна была вызваться при отказе по Content-Type"
