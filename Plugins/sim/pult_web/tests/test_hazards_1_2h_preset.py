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

_MJPEG_URL = "http://127.0.0.1:8091/"
_TIMEOUT_S = 1.0
_COMMIT_CAP = 262144  # Находка 1 Task 1.2h — потолок тела /api/preset/commit.

#: Итерация 2 ревью — офлайн-харнесс реального <script> страницы (page_offline.mjs).
_PAGE_HARNESS = Path(__file__).with_name("page_offline.mjs")
_NODE = shutil.which("node")

#: Литералы разметки редактора, закреплённые планом («Закреплено после слепого
#: тестировщика», 2026-09-28) — Н5 ревью ит.1.
_PINNED_MARKUP_IDS = (
    "presetRev",
    "presetLayers",
    "presetEngineWarn",
    "btnPresetPreview",
    "btnPresetSave",
    "btnPresetUndo",
    "presetPreviewImg",
)


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


def _run_page_js(port: int, scenario: str) -> dict:
    """Прогнать НАСТОЯЩИЙ ``<script>`` страницы (``page_offline.mjs``) и разобрать
    stdout — та же техника, что в ``test_acceptance_1_2h_preset.py``."""
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


# --------------------------------------------------------------------------- #
# Итерация 2 ревью (docs/reviews/2026-09-28_task-1.2h-review.md)              #
# --------------------------------------------------------------------------- #
# Н1 [блокер] 413 отвечает ДО дренажа, дренаж ограничен потолком и таймаутом. #
# --------------------------------------------------------------------------- #


def test_oversized_declared_length_replies_413_without_reading_all(start_pult) -> None:
    """Н1: клиент, заявивший Content-Length гигабайт и приславший 64 байта,
    обязан получить 413 быстро — сервер не имеет права ждать, пока дочитает
    весь заявленный Content-Length (зонд ревью: 8 с без ответа, 22 живых
    потока вместо 3 на неисправленном коде). Дедлайн — свой daemon-поток с
    join(), не pytest-timeout (пустышка в этом окружении, см. TRAPS)."""
    _plugin, _ctx, port = start_pult()
    before_threads = threading.active_count()

    result: dict[str, Any] = {}

    def _attempt() -> None:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5.0) as sock:
                sock.sendall(
                    b"POST /api/preset/commit HTTP/1.1\r\n"
                    b"Host: 127.0.0.1:" + str(port).encode("ascii") + b"\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Content-Length: 1000000000\r\n"
                    b"\r\n"
                    b"x" * 64
                )
                sock.settimeout(5.0)
                data = b""
                while b"\r\n\r\n" not in data:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                result["data"] = data
        except OSError as exc:  # соединение оборвётся сервером после ответа — не отказ теста
            result["error"] = repr(exc)

    thread = threading.Thread(target=_attempt, daemon=True)
    started = time.monotonic()
    thread.start()
    thread.join(timeout=8.0)
    elapsed = time.monotonic() - started

    assert not thread.is_alive(), "413 не пришёл за 8 с — сервер завис на заявленном Content-Length"
    data = result.get("data", b"")
    assert data, f"нет ответа вовсе (ошибка сокета: {result.get('error')!r})"
    status_line = data.split(b"\r\n", 1)[0]
    assert b" 413 " in status_line, f"ожидался 413, получено: {status_line!r} за {elapsed:.2f} с"

    # Дренаж (до 2 с, _DRAIN_TIMEOUT_S) успевает завершиться — поток обработчика не
    # должен пережить его надолго (потоки daemon, но зонд ревью именно про их число).
    time.sleep(2.5)
    after_threads = threading.active_count()
    assert after_threads <= before_threads + 1, (
        f"живых потоков после дренажа: {after_threads} (было {before_threads}) — утечка потока"
    )


# --------------------------------------------------------------------------- #
# Н7 [minor] preset.preview без code подписывается layers_error, не scene_error #
# --------------------------------------------------------------------------- #


def test_layers_route_error_without_code_uses_layers_error_fallback(start_pult) -> None:
    """Н7: развилка ``_dispatch`` подписи отказа была двусторонней (клиент
    ``robot`` -> ``robot_error``, иначе всегда ``scene_error``) — третий клиент
    (``layers_process``, маршрут ``preset.preview``) получал чужую подпись."""
    _plugin, _ctx, port = start_pult()
    layers_client = _client_for("layers")
    assert layers_client is not None
    layers_client.responses["preset.preview"] = {"status": "error"}  # без message и без code

    status, raw = _http(port, "POST", "/api/preset/preview", {"seeds": [1]})

    assert status == 504, f"отказ preview без code -> {status}, тело: {raw[:300]!r}"
    assert json.loads(raw.decode("utf-8")) == {"ok": False, "error": "layers_error"}


# --------------------------------------------------------------------------- #
# Н2 [блокер] «Отмена» отменяет и без предшествующего сохранения              #
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(_NODE is None, reason="node недоступен в PATH")
def test_undo_restores_previous_field_value(start_pult) -> None:
    """Н2: раньше стек пополнялся только перед успешным ``commit`` — правка
    поля и клик «Отмена» БЕЗ единого сохранения оставляли новое значение
    (зонд ревью: before=0, afterUndo=15). Снимок теперь кладётся в стек при
    первом изменении формы после последней синхронизации; на бэкенд при
    отмене по-прежнему ничего не уходит (сценарий П6)."""
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None
    scene_client.responses["preset.get"] = {
        "status": "ok",
        "rev": "rev-1",
        "preset": {"layers": [{"name": "cap", "offset_px": [0, 0]}]},
    }

    out = _run_page_js(port, "preset_undo_restores_field")

    assert out["before"] == "0", f"поле до правки должно быть 0: {out!r}"
    assert out["afterUndo"] == "0", f"«Отмена» обязана вернуть прежнее значение: {out!r}"
    commit_calls = [c for c in scene_client.calls if c[0] == "preset.commit"]
    assert commit_calls == [], f"«Отмена» не должна была ничего отправить на бэкенд: {commit_calls!r}"


# --------------------------------------------------------------------------- #
# Н3 [блокер] layer.name не попадает ни в один innerHTML сырым               #
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(_NODE is None, reason="node недоступен в PATH")
def test_layer_name_is_escaped_in_markup(start_pult) -> None:
    """Н3: строка слоя раньше собиралась конкатенацией и уходила в
    ``container.innerHTML`` целиком — имя слоя с тегом доезжало до присваивания
    неэкранированным (зонд ревью: ``<img src=x onerror=...>``). Проверка —
    перехват КАЖДОЙ записи ``.innerHTML =`` в офлайн-харнессе (не только что
    страница не упала); ``revText`` доказывает, что рендер дошёл до конца, а не
    тихо провалился до записи (иначе ``innerHtmlLeaked=false`` был бы вакуумным)."""
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None
    malicious_name = "<img src=x onerror=\"fetch('/api/run')\">"
    scene_client.responses["preset.get"] = {
        "status": "ok",
        "rev": "rev-1",
        "preset": {"layers": [{"name": malicious_name, "offset_px": [0, 0]}]},
    }

    out = _run_page_js(port, "preset_layer_name_escaped")

    assert out["revText"] == "рев.: rev-1", f"страница не должна была упасть при рендере: {out!r}"
    assert out["innerHtmlLeaked"] is False, f"onerror утёк в innerHTML: {out!r}"


# --------------------------------------------------------------------------- #
# Н4 [major] engine:false / engine отсутствует / rev:null — три состояния    #
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(_NODE is None, reason="node недоступен в PATH")
def test_engine_false_shows_restart_warning(start_pult) -> None:
    """Н4: ``engine: false`` обязан сказать словами — иначе редактор молча
    врёт «сохранено и поехало» (план, «Закреплено после слепого тестировщика»,
    2026-09-28); logикa уже верна, теста не было."""
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None
    scene_client.responses["preset.get"] = {
        "status": "ok",
        "rev": "rev-1",
        "preset": {"layers": []},
        "engine": False,
    }

    out = _run_page_js(port, "preset_state_probe")

    assert out["engineWarnText"] != "", f"engine=false должен дать непустой текст предупреждения: {out!r}"
    assert out["saveDisabled"] is False, f"engine=false не должен блокировать «Сохранить»: {out!r}"


@pytest.mark.skipif(_NODE is None, reason="node недоступен в PATH")
def test_engine_absent_shows_no_warning(start_pult) -> None:
    """Н4: ``engine`` отсутствует в ответе (форма двойников приёмки — 3 ключа)
    -> «неизвестно», не «false» — страница не должна врать про состояние,
    которое не проверяла (сравнение ``=== false``, не отрицание)."""
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None
    scene_client.responses["preset.get"] = {
        "status": "ok",
        "rev": "rev-1",
        "preset": {"layers": []},
    }

    out = _run_page_js(port, "preset_state_probe")

    assert out["engineWarnText"] == "", f"engine отсутствует -> текст должен быть пуст: {out!r}"


@pytest.mark.skipif(_NODE is None, reason="node недоступен в PATH")
def test_rev_null_blocks_save(start_pult) -> None:
    """Н4: ``rev: null`` (пресет собран из каталога, не из ``.yaml``) -> текст
    про недоступность и «Сохранить» заблокировано."""
    _plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None
    scene_client.responses["preset.get"] = {
        "status": "ok",
        "rev": None,
        "preset": {"layers": []},
        "engine": True,
    }

    out = _run_page_js(port, "preset_state_probe")

    assert out["saveDisabled"] is True, f"rev=null должен блокировать «Сохранить»: {out!r}"
    assert "нет" in out["revText"], f"revText должен сказать про недоступность: {out!r}"


# --------------------------------------------------------------------------- #
# Н5 [major] закреплённые планом id разметки редактора, не подстроки H6      #
# --------------------------------------------------------------------------- #


def test_preset_section_markup_has_pinned_ids(start_pult) -> None:
    """Н5: H6 приёмки ищет подстроки и ловит посторонние id (``btnPresetPreview``
    содержит "rev" через "P-rev-iew"); из семи литералов, закреплённых планом,
    в тестах встречался ровно один. Проверка — точное вхождение ``id="<литерал>"``
    по всем семи в сыром HTML (``GET /``, не через ``page_offline.mjs`` — тот
    же довод, что у H6: харнесс создаёт фиктивный элемент под любой id)."""
    _plugin, _ctx, port = start_pult()
    status, raw = _http(port, "GET", "/")
    html = raw.decode("utf-8")
    assert status == 200

    missing = [name for name in _PINNED_MARKUP_IDS if f'id="{name}"' not in html]
    assert not missing, f"в разметке не найдены закреплённые id: {missing!r}"


# --------------------------------------------------------------------------- #
# Ревью итерации 2: таймаут дренажа не смеет резать валидное тело команды      #
# --------------------------------------------------------------------------- #


def test_slow_but_valid_body_is_not_cut_by_drain_timeout(start_pult) -> None:
    """Лечение Н1 внесло регрессию: таймаут стоял атрибутом ``timeout`` КЛАССА
    обработчика, поэтому ``socketserver.StreamRequestHandler.setup()`` вешал его
    на любое чтение. Легитимный клиент, шлющий валидное тело с паузой длиннее
    таймаута, получал обрыв соединения вместо ответа (замер ревью ит.2: пауза
    2.8 с посреди тела ``/api/preset/commit`` -> ``WinError 10053``, ни 413, ни
    408, ни какого-либо HTTP-ответа, команда до бэкенда не доходила).

    Здесь тело уходит двумя кусками с паузой 2.8 с — заведомо больше
    ``_DRAIN_TIMEOUT_S`` (2.0 с). Дедлайн — свой daemon-поток с ``join()``:
    ``pytest.mark.timeout`` в этом окружении пустышка (плагин не установлен).
    """
    plugin, _ctx, port = start_pult()
    scene_client = _client_for("camera")
    assert scene_client is not None, "нет клиента процесса сцены"
    scene_client.responses["preset.commit"] = {"status": "ok", "rev": "rev-2"}

    body = json.dumps({"preset": {"layers": []}, "base_rev": "rev-1"}).encode("utf-8")
    head, tail = body[:10], body[10:]
    result: dict[str, Any] = {}

    def _attempt() -> None:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=15.0) as sock:
                sock.sendall(
                    b"POST /api/preset/commit HTTP/1.1\r\n"
                    b"Host: 127.0.0.1:" + str(port).encode("ascii") + b"\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
                    b"\r\n" + head
                )
                time.sleep(2.8)  # дольше _DRAIN_TIMEOUT_S — медленный, но честный клиент
                sock.sendall(tail)
                data = b""
                while b"\r\n\r\n" not in data:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                result["data"] = data
        except OSError as exc:
            result["error"] = repr(exc)

    thread = threading.Thread(target=_attempt, daemon=True)
    thread.start()
    thread.join(timeout=20.0)

    assert not thread.is_alive(), "ответ не пришёл за 20 с"
    data = result.get("data", b"")
    assert data, f"соединение оборвано без ответа: {result.get('error')!r}"
    status_line = data.split(b"\r\n", 1)[0]
    assert b" 200 " in status_line, f"медленное валидное тело -> {status_line!r}"
    assert scene_client.calls, "команда preset.commit до бэкенда не дошла"
