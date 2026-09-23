# -*- coding: utf-8 -*-
"""RED-приёмка Task 5.3a — правда сцены на пульте (маршруты + раздел страницы).

Независимый tester, worktree на коммите ``6f94201f`` (контракт лида 5.3, ред. 3,
plans/line-sim/phase-5-contract-5.3.md) — ДО реализации 5.3a. Источник контракта —
ТОЛЬКО §1, §2 и буллет «Тестер» из «Кто что пишет (5.3a)» этого файла плана.
Диффа реализации, ``_impl/`` (в этом плагине их нет — весь код в ``plugin.py``) и
тестов автора тестер не видел и не читал; блиндность в этой задаче обеспечена
воркtree на коммите ДО правки — заглядывать было физически некуда.

**§1 — маршруты.**

- Конфиг ``scene_process`` (дефолт ``"camera"``), второй ``DeviceHubClient(ctx,
  target_process=scene_process, default_timeout=timeout_s)`` — не тот же клиент,
  что для ``robot_process``.
- ``GET /api/truth`` -> команда ``truth.status`` в процесс сцены. Правило ответа —
  как у ``/api/journal`` (см. ``test_pult_journal_routes.py``): ``dict`` со
  ``status != "error"`` отдаётся как есть с кодом 200; ``status == "error"`` или
  не-``dict`` -> 504 ``{"ok": false, "error": <message>}``.
- ``POST /api/truth/reset`` -> команда ``truth.reset`` в процесс сцены. Тело —
  те же правила, что у прочих ``POST`` (415/413/400 до вызова команды; см.
  ``test_bad_json_400_unknown_404_oversize_413`` и
  ``test_non_json_content_type_rejected_415`` в существующих тестах этого плагина
  — точные коды и литералы ответов оттуда, не догадка).
- Проверка ``Host`` (403) — общая для всех маршрутов (см. ниже, почему один из
  тестов этого файла предсказуемо ЗЕЛЁНЫЙ уже сегодня).
- ``belt.*``/``sim_robot.*`` — только в ``robot``, ``truth.*`` — только в процесс
  сцены; маршрут не путает адресата.

**§2 — раздел страницы «Правда сцены».** ``<h2>Правда сцены</h2>``, ``div#truth``,
``button#btnTruthReset``. Опрос ``/api/truth`` раз в 1000 мс; клик по кнопке —
``POST /api/truth/reset`` и сразу повторный опрос. Текст строки — литерал из
плана (см. ``_EXPECTED_TRUTH_LINE_FULL``/``_NULL`` ниже, скопирован дословно).
Не ``ok`` / сбой запроса -> «правда недоступна»; журнал и статус ленты не должны
от этого зависеть (проверено отдельным тестом).

**Харнесс.** Фейковый ``DeviceHubClient`` — тот же шов и та же техника, что в
``test_pult_journal_routes.py`` (Task 5.1, уже ЗЕЛЁНЫЙ ``test_...`` подтверждает
патч по имени в модуле плагина работоспособным — не догадка тестера). Отличие
от 5.1: здесь плагин создаёт ДВА клиента (``robot`` и ``scene_process``), поэтому
двойник различается по ``target_process`` — заведён ``_client_for(name)`` поверх
общего ``_FakeDeviceHubClient.instances``, а не единственный ``client`` из
фикстуры. ``start_pult`` — фабрика (а не готовый плагин), т.к.
``test_configured_scene_process_is_honoured`` требует свой конфиг
(``scene_process="cam2"``) — единственный тест этого файла, где конфиг не дефолтный.

Страница — ``page_offline.mjs`` (реальный ``<script>`` через ``node:vm``, техника
ревьюера Task 2.3b): добавлены сценарии ``truth_line``/``truth_unavailable``/
``truth_reset`` в конец существующей цепочки ``if/else`` — старые сценарии не
тронуты.
"""

from __future__ import annotations

import http.client
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

#: §2, литерал первого примера (полные счётчики, pick_error не null).
_COUNTERS_FULL = {
    "caught": 2,
    "caught_defect": 1,
    "caught_ok": 1,
    "missed": 1,
    "missed_defect": 0,
    "missed_ok": 1,
    "dup_jobs": 1,
    "false_alarm": 1,
    "false_alarm_frozen_xy": 0,
    "untracked_jobs": 0,
    "on_belt": 0,
    "pick_error_mean_mm": 1.0,
    "pick_error_max_mm": 1.5,
}
_EXPECTED_TRUTH_LINE_FULL = (
    "поймано 2 (брак 1 / годных 1) · пропущено 1 (брак 0 / годных 1) · "
    "лишних заданий 1 · ложных тревог 1 (повтор кадра 0) · на ленте 0 · "
    "ошибка захвата ср 1.00 / макс 1.50 мм"
)

#: §2, тот же набор, pick_error_* -> null.
_COUNTERS_NULL_ERROR = {**_COUNTERS_FULL, "pick_error_mean_mm": None, "pick_error_max_mm": None}
_EXPECTED_TRUTH_LINE_NULL = (
    "поймано 2 (брак 1 / годных 1) · пропущено 1 (брак 0 / годных 1) · "
    "лишних заданий 1 · ложных тревог 1 (повтор кадра 0) · на ленте 0 · "
    "ошибка захвата ср — / макс — мм"
)


# --------------------------------------------------------------------------- #
# Двойник DeviceHubClient — как в test_pult_journal_routes.py, + raw_responses #
# --------------------------------------------------------------------------- #


class _FakeDeviceHubClient:
    """Двойник по имени конструктора ``DeviceHubClient`` (та же форма, что в 5.1).

    ``raw_responses`` — в отличие от ``responses`` (всегда ``dict(...)``-обёрнут),
    отдаёт значение КАК ЕСТЬ — нужно для сценария «не-dict ответ команды» (§1,
    "status == error ИЛИ не-dict -> 504").
    """

    instances: list["_FakeDeviceHubClient"] = []

    def __init__(self, ctx: Any, target_process: str = "robot", default_timeout: float = 2.0) -> None:
        self.ctx = ctx
        self.target_process = target_process
        self.default_timeout = default_timeout
        self.calls: list[tuple[str, dict]] = []
        self.responses: dict[str, dict] = {}
        self.raw_responses: dict[str, Any] = {}
        _FakeDeviceHubClient.instances.append(self)

    def request(self, command: str, args: dict | None = None, timeout: float | None = None) -> dict:
        args = dict(args or {})
        self.calls.append((command, args))
        if command in self.raw_responses:
            return self.raw_responses[command]
        return dict(self.responses.get(command, {"status": "ok", "echo": args}))


def _client_for(target_process: str) -> "_FakeDeviceHubClient | None":
    """Последний созданный двойник с данным ``target_process`` (или ``None``)."""
    matches = [c for c in _FakeDeviceHubClient.instances if c.target_process == target_process]
    return matches[-1] if matches else None


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


def _http_with_headers(port: int, method: str, path: str, body: bytes | None, headers: dict) -> tuple[int, bytes]:
    """Как ``_http``, но с полным контролем заголовков (нужно для 415 и чужого Host)."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5.0)
    try:
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def _run_page_js(port: int, scenario: str) -> dict:
    """Прогнать НАСТОЯЩИЙ ``<script>`` страницы (``page_offline.mjs``) и разобрать stdout."""
    assert _NODE is not None, "node недоступен в PATH — офлайн-JS-тесты этого файла пропущены"
    result = subprocess.run(
        [_NODE, str(_PAGE_HARNESS), str(port), scenario],
        capture_output=True,
        text=True,
        timeout=15.0,
    )
    assert result.returncode == 0, f"page_offline.mjs упал: stdout={result.stdout!r} stderr={result.stderr!r}"
    return json.loads(result.stdout) if result.stdout.strip() else {}


@pytest.fixture
def start_pult(monkeypatch: pytest.MonkeyPatch):
    """Фабрика: плагин на свободном порту с фейковым ``DeviceHubClient``.

    Фабрика (не готовый плагин, как в ``test_pult_journal_routes.py``), т.к.
    ``test_configured_scene_process_is_honoured`` нужен свой ``scene_process``
    в конфиге — единственное отличие от конфига по умолчанию в этом файле.
    """
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
# §1 — GET /api/truth                                                         #
# --------------------------------------------------------------------------- #


def test_get_truth_goes_to_scene_process_and_passes_through(start_pult) -> None:
    """GET /api/truth -> truth.status в процесс сцены (дефолт "camera"), тело как есть."""
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None, "нет DeviceHubClient с target_process='camera' — второй клиент из §1 не создан"
    fake_response = {"status": "ok", "counters": {"caught": 2, "on_belt": 0}, "recent": []}
    scene_client.responses["truth.status"] = fake_response

    status, raw, _headers = _http(port, "GET", "/api/truth")

    assert status == 200, f"GET /api/truth -> {status}, тело: {raw[:300]!r}"
    body = json.loads(raw.decode("utf-8"))
    assert body == fake_response, f"тело ответа не равно ответу двойника как есть: {body!r}"
    assert scene_client.calls == [("truth.status", {})], (
        f"процесс сцены получил не ровно один truth.status с пустым телом: {scene_client.calls!r}"
    )


def test_configured_scene_process_is_honoured(start_pult) -> None:
    """scene_process конфигурируем (дефолт "camera") — здесь переопределён на "cam2"."""
    _plugin, _ctx, port = start_pult(scene_process="cam2")
    scene_client = _client_for("cam2")
    assert scene_client is not None, "нет DeviceHubClient с target_process='cam2' — конфиг scene_process не читается"
    scene_client.responses["truth.status"] = {"status": "ok", "counters": {}}

    status, _raw, _headers = _http(port, "GET", "/api/truth")

    assert status == 200
    assert scene_client.calls == [("truth.status", {})]
    default_camera_client = _client_for("camera")
    assert default_camera_client is None, (
        "при scene_process='cam2' не должно быть отдельного клиента с target_process='camera'"
    )


@pytest.mark.parametrize(
    "raw_reply",
    [
        pytest.param({"status": "error", "message": "boom"}, id="status_error"),
        pytest.param(["not", "a", "dict"], id="non_dict"),
    ],
)
def test_get_truth_error_or_non_dict_is_504(start_pult, raw_reply: Any) -> None:
    """status == "error" или не-dict -> 504 {"ok": false, "error": ...} (как у /api/journal)."""
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None, "нет клиента процесса сцены"
    scene_client.raw_responses["truth.status"] = raw_reply

    status, raw, _headers = _http(port, "GET", "/api/truth")

    assert status == 504, f"GET /api/truth -> {status}, тело: {raw[:300]!r}"
    body = json.loads(raw.decode("utf-8"))
    assert body.get("ok") is False, f"504 без ok:false: {body!r}"
    assert "error" in body, f"504 без ключа error: {body!r}"


# --------------------------------------------------------------------------- #
# §1 — POST /api/truth/reset                                                  #
# --------------------------------------------------------------------------- #


def test_post_truth_reset_goes_to_scene_process(start_pult) -> None:
    """POST /api/truth/reset -> truth.reset в процесс сцены, тело ответа — как есть."""
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None, "нет клиента процесса сцены"
    scene_client.responses["truth.reset"] = {"status": "ok"}

    status, raw, _headers = _http(port, "POST", "/api/truth/reset", {})

    assert status == 200, f"POST /api/truth/reset -> {status}, тело: {raw[:300]!r}"
    body = json.loads(raw.decode("utf-8"))
    assert body == {"status": "ok"}
    assert scene_client.calls == [("truth.reset", {})], (
        f"процесс сцены получил не ровно один truth.reset с пустым телом: {scene_client.calls!r}"
    )


def test_truth_reset_bad_body_never_reaches_command(start_pult) -> None:
    """415/413/400 до вызова команды — те же правила и литералы, что у остальных POST.

    Коды и точные тела ответов скопированы из уже существующих зелёных тестов этого
    плагина (``test_bad_json_400_unknown_404_oversize_413``,
    ``test_non_json_content_type_rejected_415`` в ``test_pult_web.py`` /
    ``test_pult_web_hazards.py``) — не догадка, а перенос подтверждённого поведения
    общего для всех POST-маршрутов кода на новый путь.
    """
    _plugin, _ctx, port = start_pult()

    status_415, raw_415 = _http_with_headers(
        port, "POST", "/api/truth/reset", b'{"a": 1}', {"Content-Type": "text/plain"}
    )
    assert status_415 == 415, f"text/plain -> {status_415}, тело: {raw_415[:200]!r}"
    assert json.loads(raw_415) == {"ok": False, "error": "unsupported_media_type"}

    status_bad, raw_bad, _h = _http(port, "POST", "/api/truth/reset", b"{not-valid-json")
    assert status_bad == 400, f"кривой JSON -> {status_bad}, тело: {raw_bad[:300]!r}"
    assert json.loads(raw_bad.decode("utf-8")) == {"ok": False, "error": "bad_json"}

    oversize_body = json.dumps({"pad": "x" * 4200}).encode("utf-8")
    assert len(oversize_body) > 4096, "тестовое тело должно реально превышать 4 КБ"
    status_413, raw_413, _h = _http(port, "POST", "/api/truth/reset", oversize_body)
    assert status_413 == 413, f"тело > 4КБ -> {status_413}, тело: {raw_413[:300]!r}"

    scene_client = _client_for("camera")
    scene_calls = scene_client.calls if scene_client is not None else []
    robot_client = _client_for("robot")
    robot_calls = robot_client.calls if robot_client is not None else []
    assert scene_calls == [], f"кривое тело не должно было дойти до команды (сцена): {scene_calls!r}"
    assert robot_calls == [], f"кривое тело не должно было дойти до команды (robot): {robot_calls!r}"


# --------------------------------------------------------------------------- #
# §1 — Host-страж и адресация                                                 #
# --------------------------------------------------------------------------- #


def test_truth_routes_forbidden_host_403(start_pult) -> None:
    """Чужой Host -> 403 на обоих новых маршрутах.

    ПРЕДСКАЗАНИЕ: этот тест может оказаться ЗЕЛЁНЫМ уже сегодня, до реализации
    5.3a. ``_host_allowed()`` в ``do_GET``/``do_POST`` (plugin.py, строки 364-368,
    386-389) выполняется ПЕРВОЙ строкой, раньше любого сопоставления пути —
    чужой ``Host`` получает 403 независимо от того, существует ли ``/api/truth``
    как маршрут. Если так и оказалось зелёным — см. итоговый отчёт, это не
    ошибка теста, а совпадение с §1 «проверка Host — та же, что у остальных
    маршрутов», которая уже реализована для ВСЕХ путей.
    """
    _plugin, _ctx, port = start_pult()

    status_get, raw_get = _http_with_headers(port, "GET", "/api/truth", None, {"Host": "rebind.evil.example"})
    assert status_get == 403, f"GET /api/truth с чужим Host -> {status_get}, тело: {raw_get[:200]!r}"
    assert json.loads(raw_get) == {"ok": False, "error": "forbidden_host"}

    status_post, raw_post = _http_with_headers(
        port,
        "POST",
        "/api/truth/reset",
        b"{}",
        {"Content-Type": "application/json", "Host": "rebind.evil.example"},
    )
    assert status_post == 403, f"POST /api/truth/reset с чужим Host -> {status_post}, тело: {raw_post[:200]!r}"
    assert json.loads(raw_post) == {"ok": False, "error": "forbidden_host"}


def test_truth_never_addressed_to_robot_and_belt_journal_still_are(start_pult) -> None:
    """truth.* не должен попадать в клиент robot; belt.*/sim_robot.* — по-прежнему в robot.

    Ловит перепутанный адресат: если реализация случайно отправит ``truth.status``
    в клиент ``robot`` вместо клиента сцены, эта проверка это поймает (тело не
    совпадёт с ответом, выставленным ТОЛЬКО на клиенте сцены, а вызов появится в
    ``robot_client.calls``), в отличие от голой проверки кода ответа.
    """
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None, "нет клиента процесса сцены"
    scene_only_reply = {"status": "ok", "counters": {"marker": "scene-only"}}
    scene_client.responses["truth.status"] = scene_only_reply

    robot_client = _client_for("robot")
    assert robot_client is not None, "нет клиента robot (должен создаваться независимо от сцены)"
    robot_client.responses["sim_robot.journal"] = {"status": "ok", "counters": {}, "recent": []}

    status_truth, raw_truth, _h = _http(port, "GET", "/api/truth")
    status_journal, raw_journal, _h2 = _http(port, "GET", "/api/journal")

    assert status_truth == 200, f"GET /api/truth -> {status_truth}, тело: {raw_truth[:300]!r}"
    assert json.loads(raw_truth) == scene_only_reply, (
        "тело /api/truth не совпало с ответом, заведённым ТОЛЬКО на клиенте сцены — похоже, команда ушла не туда"
    )
    assert status_journal == 200, f"GET /api/journal -> {status_journal}, тело: {raw_journal[:300]!r}"

    truth_calls_on_robot = [c for c in robot_client.calls if c[0] == "truth.status"]
    assert truth_calls_on_robot == [], f"truth.status попал в клиент robot: {truth_calls_on_robot!r}"
    journal_calls_on_scene = [c for c in scene_client.calls if c[0] == "sim_robot.journal"]
    assert journal_calls_on_scene == [], f"sim_robot.journal попал в клиент сцены: {journal_calls_on_scene!r}"
    assert ("sim_robot.journal", {}) in robot_client.calls, "sim_robot.journal должен был дойти до robot"


# --------------------------------------------------------------------------- #
# §2 — страница, раздел «Правда сцены»                                       #
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(_NODE is None, reason="node недоступен в PATH")
def test_page_truth_line_literal(start_pult) -> None:
    """Текст #truth — литерал §2 дословно, включая "—" при pick_error_* = null."""
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None, "нет клиента процесса сцены"

    scene_client.responses["truth.status"] = {"status": "ok", "counters": dict(_COUNTERS_FULL)}
    out_full = _run_page_js(port, "truth_line")
    assert out_full.get("truthText") == _EXPECTED_TRUTH_LINE_FULL, (
        f"полные счётчики: ожидали {_EXPECTED_TRUTH_LINE_FULL!r}, страница показала {out_full.get('truthText')!r}"
    )

    scene_client.responses["truth.status"] = {"status": "ok", "counters": dict(_COUNTERS_NULL_ERROR)}
    out_null = _run_page_js(port, "truth_line")
    assert out_null.get("truthText") == _EXPECTED_TRUTH_LINE_NULL, (
        f"pick_error_*=null: ожидали {_EXPECTED_TRUTH_LINE_NULL!r}, страница показала {out_null.get('truthText')!r}"
    )


@pytest.mark.skipif(_NODE is None, reason="node недоступен в PATH")
def test_page_truth_unavailable_and_journal_independent(start_pult) -> None:
    """Процесс сцены отвечает ошибкой -> «правда недоступна», журнал работает как раньше."""
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None, "нет клиента процесса сцены"
    scene_client.responses["truth.status"] = {"status": "error", "message": "scene_down"}

    robot_client = _client_for("robot")
    assert robot_client is not None, "нет клиента robot"
    robot_client.responses["sim_robot.journal"] = {
        "status": "ok",
        "counters": {"jobs": 1, "dups": 0, "done": 1, "reads": 5, "dups_same_capture": 0, "dups_tracked": 0},
        "recent": [],
    }

    out = _run_page_js(port, "truth_unavailable")

    assert out.get("truthText") == "правда недоступна", (
        f"процесс сцены отказал (504), страница показала: {out.get('truthText')!r}"
    )
    assert out.get("journalText") not in (None, "", "журнал недоступен"), (
        f"журнал не должен зависеть от отказа сцены, страница показала: {out.get('journalText')!r}"
    )


@pytest.mark.skipif(_NODE is None, reason="node недоступен в PATH")
def test_page_truth_reset_posts_then_repolls(start_pult) -> None:
    """Клик #btnTruthReset -> POST /api/truth/reset, сразу повторный опрос."""
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None, "нет клиента процесса сцены"
    scene_client.responses["truth.status"] = {"status": "ok", "counters": dict(_COUNTERS_FULL)}
    scene_client.responses["truth.reset"] = {"status": "ok"}

    out = _run_page_js(port, "truth_reset")

    reset_calls = [c for c in scene_client.calls if c[0] == "truth.reset"]
    assert reset_calls == [("truth.reset", {})], (
        f"клик по кнопке сброса не привёл ровно к одному truth.reset: {reset_calls!r}"
    )
    assert out.get("truthText") == _EXPECTED_TRUTH_LINE_FULL, (
        f"после сброса и повторного опроса ожидали {_EXPECTED_TRUTH_LINE_FULL!r}, "
        f"страница показала {out.get('truthText')!r}"
    )


# --------------------------------------------------------------------------- #
# Лид, после break-injection 5.3a: два пробела, которые не ловил ни один тест.
# --------------------------------------------------------------------------- #

_COUNTERS_ZERO = {key: 0 for key in _COUNTERS_FULL} | {"pick_error_mean_mm": None, "pick_error_max_mm": None}
_EXPECTED_TRUTH_LINE_ZERO = (
    "поймано 0 (брак 0 / годных 0) · пропущено 0 (брак 0 / годных 0) · "
    "лишних заданий 0 · ложных тревог 0 (повтор кадра 0) · на ленте 0 · "
    "ошибка захвата ср — / макс — мм"
)


@pytest.mark.skipif(_NODE is None, reason="node недоступен в PATH")
def test_page_truth_reset_repolls_before_next_interval(start_pult) -> None:
    """Инъекция I8 (сброс без ``.then(pollTruth)``) выживала: двойник отдавал те же
    счётчики до и после сброса. Здесь ``truth.reset`` обнуляет ответ ``truth.status``.
    Сценарий ``truth_reset`` кликает на 1200 мс и читает на 1500 мс, а плановый опрос
    идёт на 1000 и 2000 мс, так что нули за это окно может показать только повторный
    опрос сразу после сброса."""
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None, "нет клиента процесса сцены"
    scene_client.responses["truth.status"] = {"status": "ok", "counters": dict(_COUNTERS_FULL)}
    original_request = scene_client.request

    def request(command: str, args: dict | None = None, timeout: float | None = None) -> dict:
        if command == "truth.reset":
            scene_client.responses["truth.status"] = {"status": "ok", "counters": dict(_COUNTERS_ZERO)}
        return original_request(command, args, timeout)

    scene_client.request = request  # type: ignore[method-assign]

    out = _run_page_js(port, "truth_reset")

    assert out.get("truthText") == _EXPECTED_TRUTH_LINE_ZERO, (
        f"после сброса страница не перечитала правду до планового опроса: {out.get('truthText')!r}"
    )


@pytest.mark.skipif(_NODE is None, reason="node недоступен в PATH")
def test_page_truth_non_ok_status_with_200_is_unavailable(start_pult) -> None:
    """Инъекция I6b (ветка ``else`` не пишет «правда недоступна») выживала. Ответ без
    ``status: "error"`` пульт отдаёт с кодом 200 (§1), и страница обязана сама отличить
    не-``ok`` от счётчиков (§2)."""
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None, "нет клиента процесса сцены"
    scene_client.responses["truth.status"] = {"status": "busy"}

    out = _run_page_js(port, "truth_line")

    assert out.get("truthText") == "правда недоступна", (
        f"ответ 200 со status != ok, страница показала: {out.get('truthText')!r}"
    )


# --------------------------------------------------------------------------- #
# Лид, после ревью 5.3a (итерация 1): находки 1–4.
# --------------------------------------------------------------------------- #


def test_page_markup_has_truth_section_after_journal(start_pult) -> None:
    """Находка 1: ``page_offline.mjs`` создаёт элемент под любой id, поэтому удалённую
    разметку раздела не ловил ни один тест страницы. Проверяем отданный HTML."""
    _plugin, _ctx, port = start_pult()
    status, body, _headers = _http(port, "GET", "/")
    html = body.decode("utf-8")
    assert status == 200
    assert "<h2>Правда сцены</h2>" in html
    assert '<div id="truth">' in html
    assert '<button id="btnTruthReset">Сброс правды</button>' in html
    assert html.index("Задания от прототипа") < html.index("Правда сцены"), "раздел правды должен идти после журнала"


@pytest.mark.skipif(_NODE is None, reason="node недоступен в PATH")
@pytest.mark.parametrize(
    "later_response",
    [{"status": "error", "message": "scene_down"}, {"status": "busy"}],
    ids=["504", "200_not_ok"],
)
def test_page_truth_goes_unavailable_after_counters(start_pult, later_response: dict) -> None:
    """Находка 2: тесты «правда недоступна» проходили на пустом начальном тексте
    харнесса. Здесь первый опрос (0 мс) отдаёт счётчики, второй (1000 мс) — отказ,
    чтение на 1200 мс: старые счётчики на экране оставаться не должны."""
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None, "нет клиента процесса сцены"
    original_request = scene_client.request
    polls = [0]

    def request(command: str, args: dict | None = None, timeout: float | None = None) -> dict:
        if command == "truth.status":
            polls[0] += 1
            first = polls[0] == 1
            scene_client.responses["truth.status"] = (
                {"status": "ok", "counters": dict(_COUNTERS_FULL)} if first else dict(later_response)
            )
        return original_request(command, args, timeout)

    scene_client.request = request  # type: ignore[method-assign]

    out = _run_page_js(port, "truth_line")

    assert polls[0] >= 2, f"страница опросила правду {polls[0]} раз, переход не проверен"
    assert out.get("truthText") == "правда недоступна", (
        f"после отказа сцены на экране осталось: {out.get('truthText')!r}"
    )


def test_negative_content_length_is_400_and_never_reaches_scene(start_pult) -> None:
    """Находка 3: ``Content-Length: -1`` раньше давал ``rfile.read(-1)`` — чтение до EOF
    в обход 413. Сокет сырой: urllib отрицательный CL не пошлёт."""
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None, "нет клиента процесса сцены"
    body = b"{" + b'"a": 1, ' * 25_000 + b'"b": 2}'
    with socket.create_connection(("127.0.0.1", port), timeout=5.0) as sock:
        sock.sendall(
            b"POST /api/truth/reset HTTP/1.1\r\n"
            + f"Host: 127.0.0.1:{port}\r\n".encode()
            + b"Content-Type: application/json\r\nContent-Length: -1\r\nConnection: close\r\n\r\n"
            + body
        )
        sock.shutdown(socket.SHUT_WR)
        reply = b""
        while chunk := sock.recv(65536):
            reply += chunk
    head, _, payload = reply.partition(b"\r\n\r\n")
    assert head.split(b"\r\n")[0].split(b" ")[1] == b"400", head
    assert json.loads(payload) == {"ok": False, "error": "bad_length"}
    assert [c for c in scene_client.calls if c[0] == "truth.reset"] == []


def test_scene_error_without_message_is_labelled_scene(start_pult) -> None:
    """Находка 4: отказ сцены без ``message`` подписывался как ``robot_error``."""
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None, "нет клиента процесса сцены"
    scene_client.responses["truth.status"] = {"status": "error"}
    status, body, _headers = _http(port, "GET", "/api/truth")
    assert status == 504
    assert json.loads(body) == {"ok": False, "error": "scene_error"}
