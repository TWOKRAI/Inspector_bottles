# -*- coding: utf-8 -*-
"""RED-приёмка Task 6.1b — четыре ручки сцены на пульте, готовым механизмом маршрутов.

``developer``, ``plans/line-sim/phase-6-contract-6.1.md``, шаг 9 и раздел «Пульт
(6.1b)» критериев приёмки. Источник контракта — эти два места плана плюс
``Plugins/sim/scene_source/plugin.py`` (докстринги ``cmd_pause``/``cmd_flow``/
``cmd_defect_rate``/``cmd_defect_now``/``_push_control``) для формы ответов и
литерала переполнения очереди управления.

**Харнесс** — тот же приём, что в ``test_acceptance_5_3a.py`` (Task 5.3a):
фейковый ``DeviceHubClient`` по имени конструктора плагина, ``_client_for``
поверх общего ``instances``, фабрика ``start_pult``, ``page_offline.mjs`` для
двух node-тестов страницы. Новые сценарии ``scene_overloaded``/``scene_status``
добавлены в ТОТ ЖЕ ``page_offline.mjs``, что и ``truth_*`` (5.3a) / ``wire*``
(6.2) — не отдельный харнесс.

**Почему ``test_scene_error_code_survives_to_client`` не проверяет ``code``.**
``_dispatch()`` пульта (``plugin.py``, метод ``_dispatch``) схлопывает ЛЮБОЙ
``status == "error"`` в HTTP 504 ``{"ok": False, "error": <message>}`` —
типизированный ``code`` (``invalid``/``overloaded``) в HTTP-ответ не попадает.
Это известное и не исправляемое здесь поведение (правит соседняя сессия,
задача 1.2h; см. TRAPS брифа 6.1b) — тест проверяет только «не 200», а
JS-повтор на overloaded распознаёт литерал сообщения ``_push_control`` по
подстроке «переполнена» (единственный канал, доступный странице сегодня).
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
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
_TIMEOUT_S = 1.0
_PAGE_HARNESS = Path(__file__).with_name("page_offline.mjs")
_NODE = shutil.which("node")

#: Литерал ``_push_control`` (``Plugins/sim/scene_source/plugin.py``) — тот же
#: текст независимо от команды.
_OVERLOADED = {
    "status": "error",
    "code": "overloaded",
    "message": "scene_source: очередь управления переполнена — заявка отклонена",
}


# --------------------------------------------------------------------------- #
# Двойник DeviceHubClient — тот же приём, что в test_acceptance_5_3a.py        #
# --------------------------------------------------------------------------- #


class _FakeDeviceHubClient:
    """Двойник по имени конструктора ``DeviceHubClient`` (та же форма, что в 5.1/5.3a)."""

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


def _client_for(target_process: str) -> "_FakeDeviceHubClient | None":
    """Последний созданный двойник с данным ``target_process`` (или ``None``)."""
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
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _run_page_js(port: int, scenario: str) -> dict:
    """Прогнать НАСТОЯЩИЙ ``<script>`` страницы (``page_offline.mjs``) и разобрать stdout.

    ``encoding="utf-8"`` явно, а не ``text=True`` (как в образце
    ``test_acceptance_5_3a.py``) — на этой машине ``text=True`` декодирует
    stdout системной локалью (не UTF-8), из-за чего Cyrillic в JSON доходит
    искажённым и сравнение с литералом всегда ложно (воспроизведено и на
    немодифицированном ``test_acceptance_5_3a.py`` — известное, не внесённое
    этой задачей ограничение среды; см. отчёт разработчика)."""
    assert _NODE is not None, "node недоступен в PATH — офлайн-JS-тесты этого файла пропущены"
    result = subprocess.run(
        [_NODE, str(_PAGE_HARNESS), str(port), scenario],
        capture_output=True,
        encoding="utf-8",
        timeout=15.0,
    )
    assert result.returncode == 0, f"page_offline.mjs упал: stdout={result.stdout!r} stderr={result.stderr!r}"
    return json.loads(result.stdout) if result.stdout.strip() else {}


@pytest.fixture
def start_pult(monkeypatch: pytest.MonkeyPatch):
    """Плагин на свободном порту с фейковым ``DeviceHubClient`` (конфиг по умолчанию)."""
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
# Маршруты POST /api/scene/*                                                   #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "path, command, body",
    [
        ("/api/scene/pause", "scene.pause", {"paused": True}),
        ("/api/scene/flow", "scene.flow", {"interval_s": [2.0, 4.0]}),
        ("/api/scene/defect_rate", "scene.defect_rate", {"probability": 0.5}),
        ("/api/scene/defect_now", "scene.defect_now", {}),
    ],
)
def test_scene_routes_go_to_scene_process_not_robot(start_pult, path: str, command: str, body: dict) -> None:
    """Четыре POST уходят в ``_scene_client``, командой и телом КАК ЕСТЬ — не в ``robot``."""
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None, "нет DeviceHubClient с target_process='camera'"
    scene_client.responses[command] = {"status": "ok"}

    status, raw = _http(port, "POST", path, body)

    assert status == 200, f"POST {path} -> {status}, тело: {raw[:300]!r}"
    assert scene_client.calls == [(command, body)], (
        f"{path} должен был уйти в сцену как {command}({body!r}) КАК ЕСТЬ: {scene_client.calls!r}"
    )
    robot_client = _client_for("robot")
    robot_calls = robot_client.calls if robot_client is not None else []
    assert robot_calls == [], f"{path} попал в клиент robot вместо сцены: {robot_calls!r}"


def test_get_api_scene_forwards_scene_status(start_pult) -> None:
    """``GET /api/scene`` -> ``scene.status`` в процесс сцены, ответ отдан как есть."""
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None, "нет клиента процесса сцены"
    fake_response = {
        "status": "ok",
        "active": 3,
        "recent": [],
        "paused": True,
        "flow": {"interval_s": [2.0, 4.0]},
        "defect_probability": 0.3,
        "force_defect_pending": False,
    }
    scene_client.responses["scene.status"] = fake_response

    status, raw = _http(port, "GET", "/api/scene")

    assert status == 200, f"GET /api/scene -> {status}, тело: {raw[:300]!r}"
    assert json.loads(raw.decode("utf-8")) == fake_response, "тело ответа не равно ответу двойника как есть"
    assert scene_client.calls == [("scene.status", {})], (
        f"процесс сцены получил не ровно один scene.status с пустым телом: {scene_client.calls!r}"
    )


def test_scene_error_code_survives_to_client(start_pult) -> None:
    """Отказ ``{"status": "error", "code": "invalid", ...}`` не превращается в 200.

    **Обновлено Task 1.2h (Находка 2).** ``_dispatch()`` больше не схлопывает
    типизированный отказ в 504 — код читается из поля ``code`` (``invalid`` ->
    400), тело command-ответа отдаётся КАК ЕСТЬ, без обёртки ``{ok: false}``
    (см. ``plans/line-sim-layer-editor/phase-1-html-form.md``, раздел Task 1.2h, «Находка 2»).
    """
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None, "нет клиента процесса сцены"
    reply = {
        "status": "error",
        "code": "invalid",
        "message": "scene.pause: ожидается {'paused': bool}, получено {}",
    }
    scene_client.responses["scene.pause"] = reply

    status, raw = _http(port, "POST", "/api/scene/pause", {"paused": "yes"})

    # 400, а не голый "!= 200": маршрут обязан реально дойти до _dispatch() и
    # получить status=="error" код="invalid" от двойника, а не молча провалиться
    # в 404 (заглушка "любой != 200" была бы зелена и без маршрута вовсе).
    assert status == 400, f"отказ команды сцены с code=invalid -> {status}, тело: {raw[:300]!r}"
    body = json.loads(raw.decode("utf-8"))
    assert body == reply, f"тело ответа не равно ответу двойника как есть: {body!r}"
    assert scene_client.calls == [("scene.pause", {"paused": "yes"})], (
        f"кривой paused должен был всё равно дойти до scene.pause (валидация — в плагине сцены): {scene_client.calls!r}"
    )


def test_existing_routes_unchanged(start_pult) -> None:
    """``/api/run``, ``/api/status``, ``/api/truth``, ``/api/journal`` — как раньше, прежние клиенты."""
    _plugin, _ctx, port = start_pult()
    robot_client = _client_for("robot")
    scene_client = _client_for("camera")
    assert robot_client is not None, "нет клиента robot"
    assert scene_client is not None, "нет клиента процесса сцены"
    robot_client.responses["belt.run"] = {"status": "ok"}
    robot_client.responses["belt.status"] = {"status": "ok", "run": True}
    robot_client.responses["sim_robot.journal"] = {"status": "ok", "counters": {}, "recent": []}
    scene_client.responses["truth.status"] = {"status": "ok", "counters": {}}

    status_run, _raw = _http(port, "POST", "/api/run", {"freq_hz": 10.0, "reverse": False})
    status_status, _raw = _http(port, "GET", "/api/status")
    status_truth, _raw = _http(port, "GET", "/api/truth")
    status_journal, _raw = _http(port, "GET", "/api/journal")

    assert (status_run, status_status, status_truth, status_journal) == (200, 200, 200, 200), (
        status_run,
        status_status,
        status_truth,
        status_journal,
    )
    assert ("belt.run", {"freq_hz": 10.0, "reverse": False}) in robot_client.calls
    assert ("belt.status", {}) in robot_client.calls
    assert ("sim_robot.journal", {}) in robot_client.calls
    assert ("truth.status", {}) in scene_client.calls
    scene_commands = {"scene.pause", "scene.flow", "scene.defect_rate", "scene.defect_now"}
    assert all(c[0] not in scene_commands for c in robot_client.calls)


# --------------------------------------------------------------------------- #
# Страница — блок «Сцена»                                                      #
# --------------------------------------------------------------------------- #


def test_page_has_scene_block(start_pult) -> None:
    """``GET /`` содержит разметку блока «Сцена» — строковый поиск (годится только здесь)."""
    _plugin, _ctx, port = start_pult()
    status, body = _http(port, "GET", "/")
    html = body.decode("utf-8")
    assert status == 200
    assert "<h2>Сцена</h2>" in html


@pytest.mark.skipif(_NODE is None, reason="node недоступен в PATH")
def test_page_scene_retries_on_overloaded(start_pult) -> None:
    """Страница получила ``overloaded`` -> повторила ту же заявку ровно один раз."""
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None, "нет клиента процесса сцены"
    scene_client.responses["scene.defect_now"] = dict(_OVERLOADED)

    _run_page_js(port, "scene_overloaded")

    calls = [c for c in scene_client.calls if c[0] == "scene.defect_now"]
    assert len(calls) == 2, f"ожидали исходную заявку + ровно один повтор (2 вызова): {calls!r}"


@pytest.mark.skipif(_NODE is None, reason="node недоступен в PATH")
@pytest.mark.parametrize(
    "reply",
    [
        {"status": "error", "message": "timeout"},
        {"status": "error", "code": "invalid", "message": "scene.defect_now: ожидается None или {}"},
    ],
    ids=["timeout", "invalid"],
)
def test_page_scene_no_retry_on_other_errors(start_pult, reply) -> None:
    """Находка ревью 6.1b: прежний тест закреплял ЧИСЛО повторов, но не ПРИЧИНУ.

    Со сломанным `isSceneOverloaded` (повтор на ЛЮБОЙ отказ) он оставался зелёным, а
    таймаут транспорта — случай, когда заявка МОГЛА дойти — давал бы два брака вместо
    одного: `scene.defect_now` не идемпотентна. Здесь отказ НЕ `overloaded`, и вызов
    обязан быть ровно один.
    """
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None, "нет клиента процесса сцены"
    scene_client.responses["scene.defect_now"] = dict(reply)

    _run_page_js(port, "scene_overloaded")

    calls = [c for c in scene_client.calls if c[0] == "scene.defect_now"]
    assert len(calls) == 1, f"отказ не overloaded — повтора быть не должно: {calls!r}"


@pytest.mark.skipif(_NODE is None, reason="node недоступен в PATH")
def test_page_scene_polls_status(start_pult) -> None:
    """Строка состояния заполняется из ``/api/scene`` (тот же таймер, что ``/api/truth``)."""
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None, "нет клиента процесса сцены"
    scene_client.responses["scene.status"] = {
        "status": "ok",
        "active": 1,
        "recent": [],
        "paused": True,
        "flow": {"interval_s": [2.0, 4.0]},
        "defect_probability": 0.3,
        "force_defect_pending": False,
    }

    out = _run_page_js(port, "scene_status")

    assert out.get("sceneText") == "пауза=true  поток=interval_s [2, 4]  доля_брака=0.3  брак_в_очереди=false", (
        f"страница показала: {out.get('sceneText')!r}"
    )


def test_overloaded_literal_matches_scene_source() -> None:
    """Страница узнаёт отказ `overloaded` по литералу сообщения, потому что `_dispatch()`
    сегодня теряет `code`. Связка модулей закреплена здесь: переименуют сообщение в
    `scene_source` — покраснеет этот тест, а не молча перестанет работать повтор заявки.

    Берётся НАСТОЯЩИЙ ответ настоящего плагина сцены (не литерал, переписанный руками):
    заполняем очередь управления до потолка и читаем текст отказа.
    """
    from unittest.mock import MagicMock

    from Plugins.sim.scene_source.plugin import SceneSourcePlugin

    plugin = SceneSourcePlugin()
    ctx = MagicMock()
    ctx.state_proxy = None
    ctx.config = {"resolution_width": 8, "resolution_height": 8}
    plugin.configure(ctx)
    plugin._spawner = object()  # движок не нужен: важен только путь отказа очереди
    reply = {"status": "ok"}
    for _ in range(200):
        reply = plugin.cmd_defect_now({})
        if reply.get("status") == "error":
            break
    assert reply["code"] == "overloaded", "плагин сцены обязан отказывать кодом overloaded"
    message = reply["message"]
    assert "переполнена" in message, (
        "страница пульта ищет в тексте отказа подстроку «переполнена» "
        "(isSceneOverloaded в _PAGE_TEMPLATE) — текст сообщения изменился, повтор заявки умрёт"
    )


@pytest.mark.skipif(_NODE is None, reason="node недоступен в PATH")
def test_page_pause_checkbox_follows_engine(start_pult) -> None:
    """Находка ревью 6.1b: галка паузы обязана идти за движком, а не за нажатием.

    Опрос `/api/scene` отдаёт `paused: True` — галка встаёт сама, даже если оператор
    её не трогал (и наоборот: отвергнутая заявка не оставит пульт в противоречии).
    """
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None, "нет клиента процесса сцены"
    scene_client.responses["scene.status"] = {
        "status": "ok",
        "active": 0,
        "recent": [],
        "paused": True,
        "flow": {"spacing_mm": [10.0, 10.0]},
        "defect_probability": 0.0,
        "force_defect_pending": False,
    }

    out = _run_page_js(port, "scene_pause_sync")

    assert out["pauseChecked"] is True, "галка не встала по состоянию движка"


@pytest.mark.skipif(_NODE is None, reason="node недоступен в PATH")
def test_page_shows_scene_refusal_text(start_pult) -> None:
    """Находка ревью 6.1b: отказ сцены обязан быть виден оператору, а не пропадать.

    README обещал «текст показывается в строке состояния» — до этой правки страница
    поле `error` нигде не выводила, и `invalid` был невидим.
    """
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None, "нет клиента процесса сцены"
    scene_client.responses["scene.defect_rate"] = {
        "status": "error",
        "code": "invalid",
        "message": "scene.defect_rate: probability=1.5 вне диапазона [0, 1]",
    }

    out = _run_page_js(port, "scene_error_text")

    assert "отказ сцены" in out["sceneText"], out["sceneText"]
    assert "вне диапазона" in out["sceneText"], out["sceneText"]


@pytest.mark.skipif(_NODE is None, reason="node недоступен в PATH")
def test_page_shows_refusal_even_when_scene_is_down(start_pult) -> None:
    """Находка ревью 6.1b, итерация 2: отказ не имеет права прятаться за «сцена недоступна».

    Иначе `sceneError` молча ждёт восстановления сцены и всплывает минутами позже, про
    давно забытое нажатие.
    """
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None, "нет клиента процесса сцены"
    scene_client.responses["scene.defect_rate"] = {
        "status": "error",
        "code": "invalid",
        "message": "scene.defect_rate: probability=1.5 вне диапазона [0, 1]",
    }
    scene_client.responses["scene.status"] = {"status": "error", "message": "нет ответа"}

    out = _run_page_js(port, "scene_error_when_down")

    assert "сцена недоступна" in out["sceneText"], out["sceneText"]
    assert "отказ сцены" in out["sceneText"], out["sceneText"]
