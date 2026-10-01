# -*- coding: utf-8 -*-
"""RED-приёмка Task 1.2h — HTML-редактор слоёв на `pult_web` (маршруты `/api/preset*`).

Независимый tester, worktree на коммите ``0c7140d0`` (контракт лида 1.2h, ред.
плана ``plans/line-sim-layer-editor/phase-1-html-form.md``, раздел «#### Task 1.2h») — ДО реализации.
Источник контракта — раздел «Устройство (решение лида)» + «Acceptance criteria»
этого раздела плана. Диффа реализации, ``_impl/`` (в этом плагине нет — весь код
в ``plugin.py``) и тестов автора тестер не видел; блиндность обеспечена деревом
на коммите ДО правки — заглядывать было физически некуда. `Plugins/sim/pult_web/
plugin.py` прочитан ДЛЯ КОНТЕКСТА (существующие ``_COMMAND_BY_PATH``,
``_SCENE_COMMAND_BY_PATH``, ``_dispatch``, ``_MAX_BODY_BYTES``, ``do_GET``/
``do_POST``, ``_PAGE_TEMPLATE``) — это код ЧУЖОЙ задачи 5.3a (уже в дереве), а
не реализация 1.2h, которой в этом коммите нет вовсе.

**Три маршрута, два адресата (контракт).**

| Маршрут | Команда | Адресат |
|---|---|---|
| ``GET /api/preset`` | ``preset.get`` | ``scene_process`` (клиент ``camera``, уже есть) |
| ``POST /api/preset/commit`` | ``preset.commit`` | ``scene_process`` |
| ``POST /api/preset/preview`` | ``preset.preview`` | ``layers_process`` (**новый** клиент) |

**Находка 1 (потолок тела).** ``/api/preset/commit`` — 256 КБ вместо общих 4096;
прочие маршруты не меняются.
**Находка 2 (код ошибки).** Ответ команды на ошибке отдаётся КАК ЕСТЬ (не
оборачивается в ``{ok: false, error: ...}``), HTTP-код — по полю ``code``:
``invalid``/``bad_request`` → 400, ``conflict`` → 409, ``io_error`` → 500, нет
ответа от процесса → 504 (как раньше). Маршруты без ``code`` в ответе (``belt.*``/
``sim_robot.*``) ведут себя как раньше — 504.
**Находка 3 (таймаут).** ``/api/preset/preview`` — 5.0 с вместо общего дефолта
1.0 с; передаётся как аргумент ``timeout=`` в ``client.request(...)``.
Поле ``base_rev`` в теле ``preset.commit`` — литерал из прозы DESIGN
(«commit идёт с ``base_rev``»), не догадка.

**ДОГАДКА ТЕСТЕРА — id разметки редактора (H6-H8).** В отличие от 5.3a, где
контракт давал буквальный HTML (``<div id="truth">``, ``<button id=
"btnTruthReset">``), критерии H6-H8 этой задачи описывают раздел редактора
СЛОВАМИ («контейнер списка слоёв, поле rev, кнопки «превью» и «сохранить»»)
без единого литерала разметки. Тестер выбрал id по идиоме уже существующей
страницы (``btnRun``, ``btnCalib``, ``btnJournalReset``, ``btnTruthReset``,
``div#journal``, ``div#truth``):

- контейнер списка слоёв — id, содержащий ``"layer"`` (H6 ищет по подстроке,
  не по точному имени — минимальная жёсткость);
- поле ревизии — id, содержащий ``"rev"``;
- кнопки — по видимому тексту ``Превью`` / ``Сохранить`` (H6), а для реального
  прогона скрипта (H7/H8) — по конкретным id ``btnPresetSave`` и полю
  ``layer0_offset_x`` (первый слой, X координата ``offset_px``);
- форма ответа ``preset.get`` — ``{"status": "ok", "rev": ..., "preset":
  {"layers": [{"name": ..., "offset_px": [x, y]}]}}`` — тоже догадка (DESIGN
  говорит только про ``ScenePreset.to_dict()``, не про обёртку команды).

Это ЯВНАЯ находка контракта, не молчаливое допущение — см. финальный отчёт.
Разработчик либо принимает эти id, либо согласует переименование с лидом
(тот же класс проблемы, которую 5.3a избежал буквальным HTML в контракте).

**Харнесс.** Двойник ``DeviceHubClient`` — своя копия техники
``test_acceptance_5_3a.py`` (импорт между тестовыми модулями избыточен), с
добавлением ``calls_with_timeout`` (нужно H5 — проверить ПЕРЕДАННЫЙ таймаут,
не только факт вызова) и ``delay_s`` (симулировать медленный ``preset.preview``
без реального сетевого таймаута — двойник синхронный, ``timeout=`` не
исполняет сам, только записывает).

Страница — ``page_offline.mjs`` (реальный ``<script>`` через ``node:vm``);
добавлены сценарии ``preset_edit_save``/``preset_edit_conflict_then_retry`` в
конец существующей цепочки ``if/else`` — старые сценарии не тронуты.
H6 намеренно НЕ через ``page_offline.mjs``: харнесс создаёт фиктивный элемент
под ЛЮБОЙ id (находка ревью 5.3a), поэтому удаление разметки не поймать через
него — H6 разбирает сырой HTML от ``GET /``.
"""

from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
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


_MJPEG_URL = "http://127.0.0.1:8091/"
_TIMEOUT_S = 1.0
_PAGE_HARNESS = Path(__file__).with_name("page_offline.mjs")
_NODE = shutil.which("node")

#: Догадка тестера про форму ответа ``preset.get`` (см. докстринг модуля).
_SAMPLE_PRESET = {
    "status": "ok",
    "rev": "rev-1",
    "preset": {"layers": [{"name": "cap", "offset_px": [0, 0]}]},
}


# --------------------------------------------------------------------------- #
# Двойник DeviceHubClient — своя копия техники 5.3a + calls_with_timeout/delay #
# --------------------------------------------------------------------------- #


class _FakeDeviceHubClient:
    """Двойник по имени конструктора ``DeviceHubClient``.

    ``calls_with_timeout`` — сверх ``calls`` (совместимость с приёмкой 5.3a):
    H5 обязан проверить, какой ИМЕННО ``timeout`` передал плагин на маршрут
    превью (Находка 3), а не только факт вызова. ``delay_s`` — синхронная
    задержка внутри ``request()``: двойник не умеет сам обрывать по
    ``timeout=``, только фиксирует переданное значение; задержка нужна лишь
    чтобы прогнать H5 через реальный HTTP round-trip дольше типичного отклика.
    """

    instances: list["_FakeDeviceHubClient"] = []

    def __init__(self, ctx: Any, target_process: str = "robot", default_timeout: float = 2.0) -> None:
        self.ctx = ctx
        self.target_process = target_process
        self.default_timeout = default_timeout
        self.calls: list[tuple[str, dict]] = []
        self.calls_with_timeout: list[tuple[str, dict, float | None]] = []
        self.responses: dict[str, dict] = {}
        self.raw_responses: dict[str, Any] = {}
        self.delay_s: float = 0.0
        _FakeDeviceHubClient.instances.append(self)

    def request(self, command: str, args: dict | None = None, timeout: float | None = None) -> dict:
        args = dict(args or {})
        self.calls.append((command, args))
        self.calls_with_timeout.append((command, args, timeout))
        if self.delay_s:
            time.sleep(self.delay_s)
        if command in self.raw_responses:
            return self.raw_responses[command]
        return dict(self.responses.get(command, {"status": "ok", "echo": args}))


def _client_for(target_process: str) -> "_FakeDeviceHubClient | None":
    """Последний созданный двойник с данным ``target_process`` (или ``None``)."""
    matches = [c for c in _FakeDeviceHubClient.instances if c.target_process == target_process]
    return matches[-1] if matches else None


def _find_key(obj: Any, key: str) -> Any:
    """Рекурсивный поиск ключа ``key`` в ``dict``/``list`` — нужен, т.к. точная
    вложенность отправляемого пресета (``preset`` / плоско?) — догадка тестера,
    не контракт (см. докстринг модуля)."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for value in obj.values():
            found = _find_key(value, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_key(value, key)
            if found is not None:
                return found
    return None


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
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            return resp.status, resp.read(), dict(resp.headers.items())
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers.items()) if exc.headers else {}


def _run_page_js(port: int, scenario: str) -> dict:
    """Прогнать НАСТОЯЩИЙ ``<script>`` страницы (``page_offline.mjs``) и разобрать stdout."""
    assert _NODE is not None, "node недоступен в PATH — офлайн-JS-тесты этого файла пропущены"
    result = subprocess.run(
        [_NODE, str(_PAGE_HARNESS), str(port), scenario],
        capture_output=True,
        encoding="utf-8",  # не text=True: node пишет UTF-8, а системная локаль тут cp1251
        timeout=15.0,
    )
    assert result.returncode == 0, f"page_offline.mjs упал: stdout={result.stdout!r} stderr={result.stderr!r}"
    return json.loads(result.stdout) if result.stdout.strip() else {}


@pytest.fixture
def start_pult(monkeypatch: pytest.MonkeyPatch):
    """Фабрика: плагин на свободном порту с фейковым ``DeviceHubClient``."""
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
# H1 — GET /api/preset -> scene_process                                      #
# --------------------------------------------------------------------------- #


def test_h1_preset_get_goes_to_scene_process(start_pult) -> None:
    """H1: GET /api/preset -> 200, тело как есть равно ответу двойника; адресат —
    scene_process (camera), не robot."""
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None, "нет клиента процесса сцены (camera) — preset.get должен идти в него"
    scene_client.responses["preset.get"] = dict(_SAMPLE_PRESET)

    status, raw, _headers = _http(port, "GET", "/api/preset")

    assert status == 200, f"GET /api/preset -> {status}, тело: {raw[:300]!r}"
    body = json.loads(raw.decode("utf-8"))
    assert body == _SAMPLE_PRESET, f"тело ответа не равно ответу двойника как есть: {body!r}"
    assert scene_client.calls == [("preset.get", {})], (
        f"процесс сцены получил не ровно один preset.get с пустым телом: {scene_client.calls!r}"
    )
    robot_client = _client_for("robot")
    robot_calls = robot_client.calls if robot_client is not None else []
    preset_calls_on_robot = [c for c in robot_calls if c[0] == "preset.get"]
    assert preset_calls_on_robot == [], f"preset.get попал в клиент robot: {preset_calls_on_robot!r}"


# --------------------------------------------------------------------------- #
# H2 — потолок тела на маршрут commit                                        #
# --------------------------------------------------------------------------- #


def test_h2_commit_accepts_large_body_and_rejects_over_cap(start_pult) -> None:
    """H2: тело 200 КБ доходит до двойника целиком (не 4096 общий потолок);
    тело больше маршрутного потолка (256 КБ) -> 413 без вызова команды."""
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None, "нет клиента процесса сцены"
    scene_client.responses["preset.commit"] = {"status": "ok", "rev": "rev-2"}

    big_preset = {
        "base_rev": "rev-1",
        "preset": {"layers": [{"name": "cap", "offset_px": [15, 0], "pad": "x" * 200_000}]},
    }
    big_body = json.dumps(big_preset).encode("utf-8")
    assert len(big_body) > 4096, "тестовое тело должно реально превышать старый общий потолок 4096"
    assert len(big_body) < 256 * 1024, "тестовое тело для первой части должно укладываться в новый потолок 256 КБ"

    status, raw, _headers = _http(port, "POST", "/api/preset/commit", big_body)
    assert status == 200, f"POST /api/preset/commit ({len(big_body)} байт) -> {status}, тело: {raw[:300]!r}"
    assert scene_client.calls == [("preset.commit", big_preset)], (
        "двойник не увидел отправленный preset целиком (тело урезано или искажено)"
    )

    oversize_preset = {
        "base_rev": "rev-1",
        "preset": {"layers": [{"name": "cap", "pad": "x" * 300_000}]},
    }
    oversize_body = json.dumps(oversize_preset).encode("utf-8")
    assert len(oversize_body) > 256 * 1024, "тестовое тело должно реально превышать маршрутный потолок 256 КБ"

    status_413, raw_413, _h = _http(port, "POST", "/api/preset/commit", oversize_body)
    assert status_413 == 413, f"тело > 256КБ -> {status_413}, тело: {raw_413[:300]!r}"
    assert json.loads(raw_413) == {"ok": False, "error": "too_large"}
    assert scene_client.calls == [("preset.commit", big_preset)], (
        "тело сверх потолка не должно было дойти до команды (счётчик вызовов не должен был вырасти)"
    )


# --------------------------------------------------------------------------- #
# H3 — код ошибки команды -> HTTP-код                                        #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "code, expected_status",
    [
        pytest.param("invalid", 400, id="invalid_400"),
        pytest.param("conflict", 409, id="conflict_409"),
        pytest.param("io_error", 500, id="io_error_500"),
    ],
)
def test_h3_error_code_maps_to_http_status(start_pult, code: str, expected_status: int) -> None:
    """H3: ответ команды с полем code отдаётся как есть, HTTP-код зависит от code
    (invalid -> 400, conflict -> 409, io_error -> 500); для conflict current_rev
    есть в теле ответа."""
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None, "нет клиента процесса сцены"
    reply: dict[str, Any] = {"status": "error", "code": code, "message": f"boom-{code}"}
    if code == "conflict":
        reply["current_rev"] = "rev-9"
    scene_client.raw_responses["preset.commit"] = reply

    status, raw, _headers = _http(port, "POST", "/api/preset/commit", {"base_rev": "rev-1", "preset": {}})

    assert status == expected_status, f"code={code} -> HTTP {status}, тело: {raw[:300]!r}"
    body = json.loads(raw.decode("utf-8"))
    assert body == reply, f"тело ответа не равно ответу двойника как есть при code={code}: {body!r}"
    if code == "conflict":
        assert "current_rev" in body, f"409 без current_rev в теле: {body!r}"


# --------------------------------------------------------------------------- #
# H4 — прежние маршруты не задеты (может быть зелёным уже сегодня)           #
# --------------------------------------------------------------------------- #


def test_h4_existing_routes_unchanged(start_pult) -> None:
    """H4: /api/run с телом 5000 байт по-прежнему 413 (общий потолок 4096 не
    поднят глобально); belt.* ошибка без code по-прежнему 504."""
    _plugin, _ctx, port = start_pult()
    oversize_body = json.dumps({"pad": "x" * 5000}).encode("utf-8")
    assert len(oversize_body) > 4096, "тестовое тело должно реально превышать 4096"

    status_413, raw_413, _h = _http(port, "POST", "/api/run", oversize_body)
    assert status_413 == 413, f"/api/run тело >4КБ -> {status_413}, тело: {raw_413[:300]!r}"

    robot_client = _client_for("robot")
    assert robot_client is not None, "нет клиента robot"
    robot_client.responses["belt.run"] = {"status": "error", "message": "boom"}
    status_err, raw_err, _h2 = _http(port, "POST", "/api/run", {"freq_hz": 1.0, "reverse": False})
    assert status_err == 504, f"belt.run ошибка без code -> {status_err}, тело: {raw_err[:300]!r}"
    assert json.loads(raw_err) == {"ok": False, "error": "boom"}


# --------------------------------------------------------------------------- #
# H5 — POST /api/preset/preview -> layers_process, свой таймаут              #
# --------------------------------------------------------------------------- #


def test_h5_preview_goes_to_layers_with_own_timeout(start_pult) -> None:
    """H5: preset.preview уходит клиенту процесса layers (не camera, не robot);
    таймаут маршрута — 5.0 с (не общий дефолт 1.0 с); двойник, отвечающий за
    2 с, укладывается в этот таймаут -> 200, не 504."""
    _plugin, _ctx, port = start_pult()
    layers_client = _client_for("layers")
    assert layers_client is not None, (
        "нет клиента с target_process='layers' — третий DeviceHubClient (1.2h) ещё не заведён"
    )
    layers_client.delay_s = 2.0
    layers_client.responses["preset.preview"] = {"status": "ok", "png_b64": "AAAA"}

    status, raw, _headers = _http(port, "POST", "/api/preset/preview", {"layers": []})

    assert status == 200, f"POST /api/preset/preview (двойник отвечает за 2с) -> {status}, тело: {raw[:300]!r}"
    body = json.loads(raw.decode("utf-8"))
    assert body == {"status": "ok", "png_b64": "AAAA"}

    calls_with_timeout = [c for c in layers_client.calls_with_timeout if c[0] == "preset.preview"]
    assert calls_with_timeout, "preset.preview не дошёл до двойника"
    assert calls_with_timeout[-1][2] == 5.0, (
        f"таймаут маршрута /api/preset/preview должен быть 5.0с (Находка 3), передан: {calls_with_timeout[-1][2]!r}"
    )

    scene_client = _client_for("camera")
    scene_calls = scene_client.calls if scene_client is not None else []
    robot_client = _client_for("robot")
    robot_calls = robot_client.calls if robot_client is not None else []
    assert [c for c in scene_calls if c[0] == "preset.preview"] == [], "preset.preview попал в клиент camera"
    assert [c for c in robot_calls if c[0] == "preset.preview"] == [], "preset.preview попал в клиент robot"


# --------------------------------------------------------------------------- #
# H6 — разметка страницы (сырой HTML, не через page_offline.mjs)             #
# --------------------------------------------------------------------------- #


def test_h6_page_markup_has_editor_section(start_pult) -> None:
    """H6: раздел редактора несёт контейнер списка слоёв, поле rev, кнопки
    «превью» и «сохранить». Проверка по сырому HTML (не через page_offline.mjs
    — находка ревью 5.3a: харнесс создаёт элемент под любой id, разметку не
    ловит). Точные id — догадка тестера (см. докстринг модуля), эвристика ниже
    ищет по подстроке id / видимому тексту кнопки, не по точному имени."""
    _plugin, _ctx, port = start_pult()
    status, body, _headers = _http(port, "GET", "/")
    html = body.decode("utf-8")
    assert status == 200

    assert re.search(r'id="[^"]*layer[^"]*"', html, re.IGNORECASE), (
        "нет контейнера списка слоёв (ожидался элемент с id, содержащим 'layer')"
    )
    assert re.search(r'id="[^"]*rev[^"]*"', html, re.IGNORECASE), (
        "нет поля ревизии (ожидался элемент с id, содержащим 'rev')"
    )
    assert re.search(r"<button[^>]*>\s*Превью\s*</button>", html), "нет кнопки «Превью»"
    assert re.search(r"<button[^>]*>\s*Сохранить\s*</button>", html), "нет кнопки «Сохранить»"


# --------------------------------------------------------------------------- #
# H7 — реальный <script>: правка -> сохранить -> commit с base_rev из get    #
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(_NODE is None, reason="node недоступен в PATH")
def test_h7_page_script_commits_with_base_rev(start_pult) -> None:
    """H7 / сценарии П1-П2: реальный <script> страницы через page_offline.mjs
    против живого сервера — правка offset_px -> «сохранить» -> preset.commit
    ушёл с base_rev из первого preset.get. Id полей ("layer0_offset_x",
    "btnPresetSave") и форма ответа preset.get — догадка тестера (см.
    докстринг модуля)."""
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None, "нет клиента процесса сцены"
    scene_client.responses["preset.get"] = dict(_SAMPLE_PRESET)
    scene_client.responses["preset.commit"] = {"status": "ok", "rev": "rev-2"}

    _run_page_js(port, "preset_edit_save")

    get_calls = [c for c in scene_client.calls if c[0] == "preset.get"]
    assert get_calls, "страница не запросила preset.get при загрузке (открыть, П1)"

    commit_calls = [c for c in scene_client.calls if c[0] == "preset.commit"]
    assert len(commit_calls) == 1, f"«сохранить» не привело ровно к одному preset.commit: {commit_calls!r}"
    _cmd, args = commit_calls[0]
    assert args.get("base_rev") == "rev-1", f"base_rev не совпал с rev первого get: {args!r}"

    offset = _find_key(args, "offset_px")
    assert offset is not None, f"в отправленном пресете не нашлось offset_px: {args!r}"
    assert list(offset) == [15, 0], f"отредактированный offset_px не дошёл до commit: {offset!r}"


# --------------------------------------------------------------------------- #
# H8 — conflict: правка не теряется, повтор уходит с current_rev             #
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(_NODE is None, reason="node недоступен в PATH")
def test_h8_page_keeps_edit_on_conflict(start_pult) -> None:
    """H8 / сценарий П5: preset.commit -> conflict -> правка не теряется;
    повторное «сохранить» уходит с current_rev (rev-9) как новым base_rev.
    offsetXAfterConflict — самая слабая проверка этого теста (см. финальный
    отчёт): харнесс создаёт фиктивный элемент под любой id, поэтому значение
    поля остаётся тем, что вписал сам сценарий, если реализация НИКОГДА не
    трогает этот id — проверка станет содержательной только если реальная
    страница читает/перезаписывает то же поле (что естественно для рендера
    строки слоя из ответа сервера)."""
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None, "нет клиента процесса сцены"
    scene_client.responses["preset.get"] = dict(_SAMPLE_PRESET)
    commit_attempts = {"n": 0}
    original_request = scene_client.request

    def request(command: str, args: dict | None = None, timeout: float | None = None) -> dict:
        if command == "preset.commit":
            commit_attempts["n"] += 1
            if commit_attempts["n"] == 1:
                scene_client.raw_responses["preset.commit"] = {
                    "status": "error",
                    "code": "conflict",
                    "current_rev": "rev-9",
                    "message": "changed by someone",
                }
            else:
                scene_client.raw_responses["preset.commit"] = {"status": "ok", "rev": "rev-10"}
        return original_request(command, args, timeout)

    scene_client.request = request  # type: ignore[method-assign]

    out = _run_page_js(port, "preset_edit_conflict_then_retry")

    commit_calls = [c for c in scene_client.calls if c[0] == "preset.commit"]
    assert len(commit_calls) == 2, f"ожидались два preset.commit (conflict + повтор): {commit_calls!r}"
    _cmd, second_args = commit_calls[1]
    assert second_args.get("base_rev") == "rev-9", (
        f"повторное сохранение должно уйти с current_rev из conflict как base_rev: {second_args!r}"
    )

    assert out.get("offsetXAfterConflict") == "15", (
        f"после conflict правка должна остаться в поле, показано: {out.get('offsetXAfterConflict')!r}"
    )
