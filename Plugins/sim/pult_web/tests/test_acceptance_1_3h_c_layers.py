# -*- coding: utf-8 -*-
"""RED-приёмка Task 1.3h-c (часть C) — слои на странице `pult_web`: добавить / заменить картинку /
удалить / выше / ниже и список PNG (до реализации).

Независимый tester вслепую, worktree `ls-13hc-c-tester`, коммит `c8fe3540` (план 1.3h-c, реализации нет).
Источник — `plans/line-sim-layer-editor/task-1.3h-c-layers.md`: разделы «Устройство страницы (c2)»,
«Acceptance criteria» C1-C10 и форма ответа бэкенда из «Устройство бэкенда (c1)». Прочитано ДЛЯ
КОНТЕКСТА (существующий код, не реализация): `_PRESET_SECTION`/`_PRESET_SCRIPT`/`_PRESET_ROUTES`,
`page_offline.mjs`, тесты 1.3h-b и 1.2h, `LayerSpec`.

Страница — НАСТОЯЩИЙ `<script>` пульта, прогнанный `page_offline.mjs` (node:vm) против живого сервера
плагина с двойниками процессов (техника `test_acceptance_1_3h_canvas.py`, его контракт п.1-9 действует
как есть: выбор слоя — кликом по непрозрачному пикселю слоя на `#presetCanvas`, «Отмена» — `btnPresetUndo`,
«Сохранить» — `btnPresetSave`, отказ раскладки — `#presetLayoutError`). Харнесс расширен (только
аддитивно): `<select>`/`<option>` (модель — в шапке `attachSelect`), шаг `select_option`, в `snap` —
`layers` (= `presetState.layers`), `form` (= `collectPresetFromFields().layers`), `rows`, `sel`,
`spritesError`.

Контракт, который пинит этот файл (всё остальное — дело реализации)
====================================================================
1. Разметка `GET /`: `<select id="presetSpriteSelect">`, `<button>` с id `btnLayerAdd`, `btnLayerSprite`
   («Заменить картинку»), `btnLayerDelete`, `btnLayerUp`, `btnLayerDown`, `btnSpritesRefresh`, элемент
   `presetSpritesError` (текст отказа списка).
2. Список: при загрузке страницы `POST /api/preset/sprites` с телом `{}` — один раз; ответ
   `{status: ok, dir, files: [{path, sprite_source}], truncated, layer_template}`. `<option value>` =
   `sprite_source`, текст = `path`; отдельный пункт со значением `class://`. `btnSpritesRefresh` — ещё
   один запрос и пересборка списка (без дублей).
3. «Добавить» (значение берётся из выбранного пункта `<select>`): копия `layer_template`, `name` — основа
   ИМЕНИ файла (последний компонент пути без расширения; `class` для `class://`), занято — `_2`, `_3`;
   слой ДОБАВЛЯЕТСЯ В КОНЕЦ (рисуется поверх) и становится выбранным.
4. «Удалить»/«Заменить картинку»/«Выше»/«Ниже» — над выбранным слоем. «Выше» — к концу списка, «Ниже» — к
   началу; выбор идёт за слоем. «Заменить» меняет ТОЛЬКО `sprite_source`.
5. Каждая операция — одна правка `presetState`, ровно одна запись «Отмена», ровно один `POST
   /api/preset/layout` с новым составом (`collectPresetFromFields()`). Ничего не изменившая операция
   («Выше» у верхнего, ничего не выбрано) — ни записи «Отмена», ни запроса.
6. Авто-слой `base` не входит в `presetState`; кнопки его не касаются.

Как измеряется «ровно одна запись» (запись undo сама по себе ненаблюдаема, а дубль/лишний снимок при
«Отмене» даёт ТО ЖЕ состояние): перед проверяемой операцией кладётся заведомо своя запись (правка поля
`layer0_offset_x` -> markPresetDirty 1.2h) либо операции идут цепочкой, и «Отмены» считаются по шагам;
лишняя или двойная запись сдвинула бы цепочку и лишняя «Отмена» вернула бы уже ПРОШЛОЕ состояние.
Негативные утверждения («ничего не изменилось») всегда идут с положительным контролем в том же тесте
(та же кнопка при выбранном слое РАБОТАЕТ) — иначе, пока кнопок нет, они были бы зелёными.
"""

from __future__ import annotations

import base64
import json
import shutil
import socket
import struct
import subprocess
import urllib.request
import zlib
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import (
    MockProcessServices,
    MockStatsManager,
)
from Plugins.sim.pult_web.plugin import PultWebPlugin

pytestmark = pytest.mark.timeout(60)

_MJPEG_URL = "http://127.0.0.1:8091/"
_PAGE_HARNESS = Path(__file__).with_name("page_offline.mjs")
_NODE = shutil.which("node")

# --------------------------------------------------------------------------- #
# Фикстура: канва объекта 200x200, центр (100, 100); спрайты по sprite_source  #
# --------------------------------------------------------------------------- #
_CANVAS_PX = 200


def _png(w: int, h: int, rgba: tuple[int, int, int, int]) -> bytes:
    """Сплошной RGBA PNG без внешних зависимостей (фильтр 0 на каждой строке)."""
    raw = b"".join(b"\x00" + bytes(rgba) * w for _ in range(h))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


#: sprite_source -> (w, h, PNG). У каждого свой цвет: страница различает слои по data-URL картинки.
#: `sprites/notrgba.png` СПЕЦИАЛЬНО отсутствует: двойник раскладки отвечает на него `invalid`
#: («нужен альфа-канал», как настоящая фабрика на не-RGBA файл).
_SPRITES: dict[str, tuple[int, int, bytes]] = {
    "base": (200, 200, _png(200, 200, (90, 90, 90, 255))),
    "sprites/disk.png": (100, 100, _png(100, 100, (30, 30, 220, 255))),
    "sprites/letter.png": (30, 30, _png(30, 30, (220, 30, 30, 255))),
    "sprites/cap.png": (20, 20, _png(20, 20, (30, 200, 30, 255))),
    "sprites/a.png": (40, 40, _png(40, 40, (230, 230, 30, 255))),
    "sprites/c.png": (60, 60, _png(60, 60, (240, 130, 20, 255))),
    "sprites/sub/b.PNG": (40, 40, _png(40, 40, (200, 30, 200, 255))),
    "sprites/sub/двойной диск.png": (40, 40, _png(40, 40, (30, 200, 200, 255))),
    "class://": (50, 50, _png(50, 50, (250, 250, 250, 255))),
}


def _data_url(source: str) -> str:
    return "data:image/png;base64," + base64.b64encode(_SPRITES[source][2]).decode("ascii")


def _layer(name: str, source: str, ox: int, oy: int, **extra: Any) -> dict:
    base = {
        "name": name,
        "mode": "static",
        "sprite_source": source,
        "offset_px": [ox, oy],
        "angle_deg": 0.0,
        "scale": 1.0,
        "augment": None,
        "defect_probability": 0.0,
        "color_rgb": None,
    }
    base.update(extra)
    return base


#: Три слоя с эксклюзивными пикселями (клик по пикселю однозначно выбирает слой, в обоих порядках):
#: disk 100x100 в центре (объект 50..150), letter 30x30 правее (145..175 x 85..115), cap 20x20 (20..40).
#: У disk неумолчательные поля — «побитово те же» после «Заменить» проверяется на них.
_DISK = _layer(
    "disk", "sprites/disk.png", 0, 0, angle_deg=12.5, scale=1.5, defect_probability=0.25, color_rgb=[10, 20, 30]
)
_LETTER = _layer("letter", "sprites/letter.png", 60, 0)
_CAP = _layer("cap", "sprites/cap.png", -70, -70)
_INITIAL = [_DISK, _LETTER, _CAP]

#: Точки клика (объект -> смещение от центра канвы, как `_screen` в тестах 1.3h-b, зум 100 %).
_AT_DISK = [0, 0]  # объект (100, 100): только disk
_AT_LETTER = [65, 0]  # объект (165, 100): только letter
_AT_CAP = [-70, -70]  # объект (30, 30): только cap

#: Шаблон слоя — как `LayerSpec(...).model_dump(mode="json")` + ОДНО поле, которого страница знать не может
#: (`future_field`): «новое поле LayerSpec попадает в шаблон само» — страница обязана взять ключи ИЗ шаблона.
_TEMPLATE = {
    "name": "_",
    "mode": "static",
    "sprite_source": "_",
    "offset_px": [0.0, 0.0],
    "angle_deg": 0.0,
    "scale": 1.0,
    "augment": None,
    "defect_probability": 0.0,
    "color_rgb": None,
    "future_field": 7,
}


def _added(name: str, source: str) -> dict:
    """Ожидаемый новый слой: шаблон с подставленными name/sprite_source (литерал, не из кода)."""
    return {
        "name": name,
        "mode": "static",
        "sprite_source": source,
        "offset_px": [0, 0],
        "angle_deg": 0,
        "scale": 1,
        "augment": None,
        "defect_probability": 0,
        "color_rgb": None,
        "future_field": 7,
    }


#: Ответ `preset.sprites` (порядок по `path`, как обещает бэкенд).
_FILES = [
    {"path": "a.png", "sprite_source": "sprites/a.png"},
    {"path": "c.png", "sprite_source": "sprites/c.png"},
    {"path": "disk.png", "sprite_source": "sprites/disk.png"},
    {"path": "notrgba.png", "sprite_source": "sprites/notrgba.png"},
    {"path": "sub/b.PNG", "sprite_source": "sprites/sub/b.PNG"},
    {"path": "sub/двойной диск.png", "sprite_source": "sprites/sub/двойной диск.png"},
]
_SPRITES_OK = {
    "status": "ok",
    "dir": "data/line_sim",
    "files": _FILES,
    "truncated": False,
    "layer_template": _TEMPLATE,
}
_A, _C, _DISK_SRC, _NOT_RGBA = "sprites/a.png", "sprites/c.png", "sprites/disk.png", "sprites/notrgba.png"
_B, _RU, _CLASS = "sprites/sub/b.PNG", "sprites/sub/двойной диск.png", "class://"


def _layout_reply(preset_layers: list[dict]) -> dict:
    """Ответ `preset.layout`: `base` + слои пресета по порядку; спрайт — по `sprite_source`.
    Геометрия — формулы 1.3h-a: `origin = round(canvas/2 + offset - size/2)`. Неизвестный спрайт -> `invalid`."""
    layers = []
    for name, source, ox, oy in [("base", "base", 0, 0)] + [
        (s["name"], s["sprite_source"], *s["offset_px"]) for s in preset_layers
    ]:
        if source not in _SPRITES:
            return {"status": "error", "code": "invalid", "message": f"слой '{name}': нужен альфа-канал ({source})"}
        w, h, _png_bytes = _SPRITES[source]
        layers.append(
            {
                "name": name,
                "png_b64": _data_url(source).split(",", 1)[1],
                "center_px": [ox, oy],
                "size_px": [w, h],
                "origin_px": [round(_CANVAS_PX / 2 + ox - w / 2), round(_CANVAS_PX / 2 + oy - h / 2)],
            }
        )
    return {"status": "ok", "class_name": "A", "canvas_px": [_CANVAS_PX, _CANVAS_PX], "layers": layers}


# --------------------------------------------------------------------------- #
# Двойники процессов и стенд                                                  #
# --------------------------------------------------------------------------- #
class _FakeDeviceHubClient:
    """Двойник `DeviceHubClient` (техника 1.2h/1.3h-b): `handlers[cmd](args) -> reply`, иначе `responses[cmd]`."""

    instances: list["_FakeDeviceHubClient"] = []

    def __init__(self, ctx: Any, target_process: str = "robot", default_timeout: float = 2.0) -> None:
        self.ctx = ctx
        self.target_process = target_process
        self.default_timeout = default_timeout
        self.calls: list[tuple[str, dict]] = []
        self.responses: dict[str, dict] = {}
        self.handlers: dict[str, Callable[[dict], dict]] = {}
        _FakeDeviceHubClient.instances.append(self)

    def request(self, command: str, args: dict | None = None, timeout: float | None = None) -> dict:
        args = json.loads(json.dumps(args or {}))  # глубокая копия: тест читает тело, каким оно ушло
        self.calls.append((command, args))
        if command in self.handlers:
            return self.handlers[command](args)
        return dict(self.responses.get(command, {"status": "ok", "echo": args}))


def _client_for(target: str) -> "_FakeDeviceHubClient":
    matches = [c for c in _FakeDeviceHubClient.instances if c.target_process == target]
    assert matches, f"нет клиента процесса {target!r}"
    return matches[-1]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def start_pult(monkeypatch: pytest.MonkeyPatch):
    """Плагин на свободном порту с фейковым `DeviceHubClient`; вернуть порт."""
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


class _Stand:
    def __init__(self, port: int, scene: _FakeDeviceHubClient, layers: _FakeDeviceHubClient) -> None:
        self.port = port
        self.scene = scene
        self.layers = layers

    def commits(self) -> list[dict]:
        return [args for cmd, args in self.scene.calls if cmd == "preset.commit"]

    def layout_requests(self) -> list[dict]:
        return [args for cmd, args in self.layers.calls if cmd == "preset.layout"]

    def sprite_requests(self) -> list[dict]:
        return [args for cmd, args in self.layers.calls if cmd == "preset.sprites"]


def _stand(
    start_pult: Callable[[], int],
    preset_layers: list[dict],
    *,
    sprites_replies: list[dict] | None = None,
    commit_replies: list[dict] | None = None,
) -> _Stand:
    """Стенд: `preset.get` — rev-1 и слои; `preset.layout` — раскладка из ПРИСЛАННОГО пресета;
    `preset.sprites` — очередь ответов (последний повторяется), по умолчанию `_SPRITES_OK`."""
    port = start_pult()
    scene = _client_for("camera")
    layers = _client_for("layers")
    initial = json.loads(json.dumps(preset_layers))
    scene.responses["preset.get"] = {"status": "ok", "rev": "rev-1", "preset": {"layers": initial}, "engine": True}
    commit_queue = list(commit_replies or [])
    counter = {"rev": 1}

    def commit(args: dict) -> dict:
        if commit_queue:
            return commit_queue.pop(0)
        counter["rev"] += 1
        return {"status": "ok", "rev": f"rev-{counter['rev']}"}

    scene.handlers["preset.commit"] = commit
    layers.handlers["preset.layout"] = lambda args: _layout_reply((args.get("preset") or {"layers": initial})["layers"])
    queue = list(sprites_replies if sprites_replies is not None else [_SPRITES_OK])

    def sprites(args: dict) -> dict:
        return json.loads(json.dumps(queue.pop(0) if len(queue) > 1 else queue[0]))

    layers.handlers["preset.sprites"] = sprites
    return _Stand(port, scene, layers)


def _run(port: int, scenario: str, payload: Any) -> dict:
    assert _NODE is not None, "node недоступен в PATH — офлайн-JS-тесты этого файла пропущены"
    result = subprocess.run(
        [_NODE, str(_PAGE_HARNESS), str(port), scenario, json.dumps(payload)],
        capture_output=True,
        encoding="utf-8",  # не text=True: node пишет UTF-8, а системная локаль тут cp1251
        timeout=30.0,
    )
    assert result.returncode == 0, (
        f"page_offline.mjs упал: stdout={result.stdout[:500]!r} stderr={result.stderr[:800]!r}"
    )
    return json.loads(result.stdout)


def _run_canvas(port: int, steps: list[dict]) -> dict:
    return _run(port, "canvas_script", steps)


# --------------------------------------------------------------------------- #
# Шаги сценария и проверки                                                    #
# --------------------------------------------------------------------------- #
_READY = {"op": "wait_drawn", "n": 4}  # base + disk + letter + cap нарисованы на канве
_READY3 = {"op": "wait_drawn", "n": 3}  # base + disk + letter (пресет из двух слоёв)
_SETTLE = {"op": "sleep", "ms": 300}
_UNDO = {"op": "press_button", "id": "btnPresetUndo"}


def _snap(tag: str, ids: list[str] | None = None) -> dict:
    return {"op": "snap", "tag": tag, "ids": ids or []}


def _pick(source: str) -> dict:
    return {"op": "select_option", "id": "presetSpriteSelect", "value": source}


def _btn(button_id: str) -> dict:
    return {"op": "press_button", "id": button_id}


def _click(at: list[float]) -> dict:
    return {"op": "click", "at": at}


def _assert_ran(out: dict) -> None:
    """Сценарий дошёл до конца: канва нарисована, все `select_option` нашли пункт в списке."""
    bad = [s for s in out["selects"] if not s["ok"]]
    assert not bad, (
        f"в <select id=presetSpriteSelect> нет пункта(ов) с таким value (список спрайтов не собран страницей): "
        f"{[(b['value'], 'есть: ' + str(b['have'])) for b in bad]}"
    )
    assert out["aborted"] is None and all(w["ok"] for w in out["waits"]), (
        f"страница не нарисовала слои раскладки на #presetCanvas: ожидания={out['waits']}"
    )


def _state(snap: dict) -> list[dict]:
    """Состав слоёв после операции; `presetState.layers` обязан совпасть с тем, что видно в форме."""
    assert snap["layers"] is not None, "presetState не загружен"
    assert snap["layers"] == snap["form"], (
        f"presetState.layers и поля формы (collectPresetFromFields) расходятся: {snap['layers']!r} vs {snap['form']!r}"
    )
    return snap["layers"]


def _eff(snap: dict) -> list[dict]:
    """ЭФФЕКТИВНОЕ состояние (то, что уйдёт в commit/раскладку): `collectPresetFromFields()`. После правки поля
    без операции `presetState` ещё старый (1.2h синхронизирует его только операциями), поэтому для снимков с
    непроведённой правкой поля сверяется форма, а не `presetState`."""
    assert snap["form"] is not None, "presetState не загружен"
    return snap["form"]


def _names(layers: list[dict]) -> list[str]:
    return [ly["name"] for ly in layers]


def _last_layout(stand: _Stand) -> list[dict]:
    reqs = stand.layout_requests()
    assert reqs, "раскладку ни разу не запросили"
    return reqs[-1]["preset"]["layers"]


# --------------------------------------------------------------------------- #
# C1 — разметка GET / (разбор HTML, НЕ харнесс: харнесс создаёт узел под любой id)                     #
# --------------------------------------------------------------------------- #
class _Ids(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: dict[str, list[str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for key, value in attrs:
            if key == "id" and value:
                self.tags.setdefault(value, []).append(tag)


def test_c1_markup_has_all_layer_editor_ids(start_pult) -> None:
    """C1: `GET /` несёт все id редактора слоёв: select, шесть кнопок и элемент текста отказа списка."""
    port = start_pult()
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as resp:
        html = resp.read().decode("utf-8")
    parser = _Ids()
    parser.feed(html)
    expected = {
        "presetSpriteSelect": "select",
        "btnLayerAdd": "button",
        "btnLayerSprite": "button",
        "btnLayerDelete": "button",
        "btnLayerUp": "button",
        "btnLayerDown": "button",
        "btnSpritesRefresh": "button",
    }
    missing = [i for i in [*expected, "presetSpritesError"] if i not in parser.tags]
    assert not missing, f"в разметке `GET /` нет id: {missing}"
    for ident, tag in expected.items():
        assert parser.tags[ident] == [tag], (
            f"id={ident!r}: ожидался ровно один <{tag}>, разметка даёт {parser.tags[ident]!r}"
        )
    assert len(parser.tags["presetSpritesError"]) == 1, (
        f"presetSpritesError не уникален: {parser.tags['presetSpritesError']!r}"
    )


# --------------------------------------------------------------------------- #
# C2 — список: один запрос при загрузке, пункты по формату; «Обновить список» #
# --------------------------------------------------------------------------- #
def test_c2_list_requested_once_and_options_built(start_pult) -> None:
    """C2: после загрузки ровно один `POST /api/preset/sprites` с телом `{}`; в `<select>` — по пункту на файл
    двойника (value = sprite_source, текст = path, порядок ответа) и ровно один пункт `class://`."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(stand.port, [_READY, {"op": "sleep", "ms": 500}, _snap("loaded")])
    posts = [e for e in out["fetchLog"] if e["path"] == "/api/preset/sprites" and e["method"] == "POST"]
    assert len(posts) == 1, f"список спрайтов должен быть запрошен ровно один раз при загрузке: {out['fetchLog']!r}"
    assert json.loads(posts[0]["body"]) == {}, f"тело запроса списка — `{{}}`: {posts[0]['body']!r}"
    assert len(stand.sprite_requests()) == 1, f"клиент процесса layers видел {stand.sprite_requests()!r}"
    options = out["snaps"]["loaded"]["sel"]["options"]
    files = [o for o in options if o["value"] != _CLASS]
    assert [o["value"] for o in files] == [f["sprite_source"] for f in _FILES], f"value пунктов-файлов: {options!r}"
    assert [o["text"] for o in files] == [f["path"] for f in _FILES], f"текст пунктов-файлов — path: {options!r}"
    assert [o["value"] for o in options].count(_CLASS) == 1, f"нужен ровно один пункт class://: {options!r}"
    assert options and all(o["text"] for o in options), f"у каждого пункта есть подпись: {options!r}"


def test_c2_refresh_rerequests_and_rebuilds_without_duplicates(start_pult) -> None:
    """«Обновить список»: ещё ровно один запрос; список пересобран по НОВОМУ ответу (без дублей и хвоста старого)."""
    second = {**_SPRITES_OK, "files": [{"path": "c.png", "sprite_source": _C}]}
    stand = _stand(start_pult, _INITIAL, sprites_replies=[_SPRITES_OK, second])
    out = _run_canvas(
        stand.port,
        [
            {"op": "sleep", "ms": 500},
            _snap("before"),
            _btn("btnSpritesRefresh"),
            {"op": "sleep", "ms": 400},
            _snap("after"),
        ],
    )
    assert len(stand.sprite_requests()) == 2, (
        f"«Обновить список» — ровно один новый запрос: {stand.sprite_requests()!r}"
    )
    before = [o["value"] for o in out["snaps"]["before"]["sel"]["options"]]
    assert before.count(_A) == 1 and len(before) == len(_FILES) + 1, f"стартовый список: {before!r}"
    after = out["snaps"]["after"]["sel"]["options"]
    assert sorted(o["value"] for o in after) == sorted([_C, _CLASS]), (
        f"после обновления в списке только c.png и class:// (список пересобран, не дописан): {after!r}"
    )


# --------------------------------------------------------------------------- #
# C3 — «Добавить»                                                             #
# --------------------------------------------------------------------------- #
def test_c3_add_appends_template_copy_last_and_selected(start_pult) -> None:
    """C3: «Добавить» a.png -> слой ПОСЛЕДНИЙ, `name == "a"`, ключи из `layer_template` (в т.ч. `future_field`),
    строка формы и её поля есть, слой выбран, раскладка запрошена ровно один раз с новым составом;
    «Отмена» возвращает прежний список слоёв целиком."""
    stand = _stand(start_pult, _INITIAL)
    ids = ["layer3_offset_x", "layer3_offset_y", "layer3_scale", "layer3_future_field"]
    out = _run_canvas(
        stand.port,
        [
            _READY,
            {"op": "sleep", "ms": 300},
            _snap("before"),
            _pick(_A),
            _btn("btnLayerAdd"),
            _SETTLE,
            _snap("after", ids),
            _UNDO,
            _SETTLE,
            _snap("undone"),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert _state(s["before"]) == _INITIAL
    after = _state(s["after"])
    assert after == [*_INITIAL, _added("a", _A)], f"состав после «Добавить» a.png: {after!r}"
    assert s["after"]["rows"] == ["disk", "letter", "cap", "a"], f"строки формы: {s['after']['rows']!r}"
    assert s["after"]["selected"] == ["a"], f"новый слой должен стать выбранным: {s['after']['selected']!r}"
    assert s["after"]["fields"] == {
        "layer3_offset_x": "0",
        "layer3_offset_y": "0",
        "layer3_scale": "1",
        "layer3_future_field": "7",
    }, f"поля формы нового слоя (форма строится из ключей шаблона): {s['after']['fields']!r}"
    assert s["after"]["layoutCount"] == s["before"]["layoutCount"] + 1, (
        f"ровно один новый запрос раскладки: было {s['before']['layoutCount']}, стало {s['after']['layoutCount']}"
    )
    assert _names(_last_layout(stand)) in (["disk", "letter", "cap", "a"], ["disk", "letter", "cap"]), "тело раскладки"
    assert _state(s["undone"]) == _INITIAL, (
        f"«Отмена» возвращает прежний список слоёв целиком: {s['undone']['layers']!r}"
    )
    assert s["undone"]["rows"] == ["disk", "letter", "cap"]


def test_c3_layout_request_carries_the_new_state(start_pult) -> None:
    """C3 (тело запроса): запрос раскладки после «Добавить» несёт ПОЛНЫЙ новый состав, включая новый слой."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(stand.port, [_READY, _pick(_A), _btn("btnLayerAdd"), _SETTLE, _snap("after")])
    _assert_ran(out)
    assert _last_layout(stand) == [*_INITIAL, _added("a", _A)], (
        f"последний preset.layout должен нести состав с добавленным слоем: {stand.layout_requests()[-1]!r}"
    )


@pytest.mark.parametrize(
    "source, expected_name",
    [
        pytest.param(_B, "b", id="subdir_and_uppercase_extension"),
        pytest.param(_RU, "двойной диск", id="cyrillic_and_space"),
        pytest.param(_CLASS, "class", id="class_marker"),
    ],
)
def test_c3_name_is_file_stem(start_pult, source: str, expected_name: str) -> None:
    """Имя нового слоя — основа имени ФАЙЛА: без каталога и без расширения (любой регистр); `class` для `class://`;
    кириллица и пробел не ломают поля формы (id по индексу) и уходят в тело раскладки."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [_READY, _pick(source), _btn("btnLayerAdd"), _SETTLE, _snap("after", ["layer3_offset_x"])],
    )
    _assert_ran(out)
    after = _state(out["snaps"]["after"])
    assert after[-1] == _added(expected_name, source), f"новый слой: {after[-1]!r}"
    assert out["snaps"]["after"]["rows"][-1] == expected_name
    assert out["snaps"]["after"]["fields"] == {"layer3_offset_x": "0"}, "поле формы нового слоя (id по индексу)"
    assert _last_layout(stand)[-1] == _added(expected_name, source)


# --------------------------------------------------------------------------- #
# C4 — уникальность имён                                                      #
# --------------------------------------------------------------------------- #
def test_c4_same_file_three_times_gives_a_a_2_a_3(start_pult) -> None:
    """C4: один файл трижды -> имена `a`, `a_2`, `a_3` (в конец, по порядку)."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [_READY, _pick(_A), _btn("btnLayerAdd"), _btn("btnLayerAdd"), _btn("btnLayerAdd"), _SETTLE, _snap("after")],
    )
    _assert_ran(out)
    after = _state(out["snaps"]["after"])
    assert _names(after) == ["disk", "letter", "cap", "a", "a_2", "a_3"], (
        f"имена после трёх «Добавить»: {_names(after)!r}"
    )
    assert out["snaps"]["after"]["selected"] == ["a_3"], "выбран последний добавленный"


def test_c4_name_taken_by_existing_preset_layer_gets_suffix(start_pult) -> None:
    """C4 (занято слоем пресета): файл `disk.png` при существующем слое `disk` -> `disk_2`; исходный `disk` цел."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(stand.port, [_READY, _pick(_DISK_SRC), _btn("btnLayerAdd"), _SETTLE, _snap("after")])
    _assert_ran(out)
    after = _state(out["snaps"]["after"])
    assert _names(after) == ["disk", "letter", "cap", "disk_2"], f"имена: {_names(after)!r}"
    assert after[0] == _DISK, "исходный слой disk не тронут"
    assert after[-1] == _added("disk_2", _DISK_SRC)


# --------------------------------------------------------------------------- #
# C5 — «Удалить»                                                              #
# --------------------------------------------------------------------------- #
def test_c5_delete_selected_and_undo_restores_position(start_pult) -> None:
    """C5: удалён выбранный СРЕДНИЙ слой: нет в presetState, в форме и в теле следующего preset.layout;
    «Отмена» вернула его на прежнее место (индекс 1 из 3)."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            _click(_AT_LETTER),
            _snap("selected"),
            _btn("btnLayerDelete"),
            _SETTLE,
            _snap("after"),
            _UNDO,
            _SETTLE,
            _snap("undone"),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert s["selected"]["selected"] == ["letter"], "контроль: клик выбрал letter"
    after = _state(s["after"])
    assert after == [_DISK, _CAP], f"состав после «Удалить»: {after!r}"
    assert s["after"]["rows"] == ["disk", "cap"], f"строки формы: {s['after']['rows']!r}"
    assert s["after"]["layoutCount"] == s["selected"]["layoutCount"] + 1, "ровно один запрос раскладки"
    assert s["undone"]["layoutCount"] == s["after"]["layoutCount"] + 1, "«Отмена» перезапрашивает раскладку"
    assert _state(s["undone"]) == _INITIAL, f"«Отмена» вернула слой на прежнее место: {s['undone']['layers']!r}"
    assert s["undone"]["rows"] == ["disk", "letter", "cap"]
    bodies = [r["preset"]["layers"] for r in stand.layout_requests()]
    assert [_names(b) for b in bodies if len(b) == 2] == [["disk", "cap"]], f"тело раскладки после удаления: {bodies!r}"


# --------------------------------------------------------------------------- #
# C6 — «Выше»/«Ниже»                                                          #
# --------------------------------------------------------------------------- #
def test_c6_up_moves_toward_end_and_selection_follows(start_pult) -> None:
    """C6: `[disk, letter]`, выбран disk, «Выше» -> `[letter, disk]`; выбран по-прежнему disk; ровно один запрос
    раскладки, тело несёт новый порядок; «Отмена» -> `[disk, letter]`."""
    initial = [_DISK, _LETTER]
    stand = _stand(start_pult, initial)
    out = _run_canvas(
        stand.port,
        [
            _READY3,
            _click(_AT_DISK),
            _snap("selected"),
            _btn("btnLayerUp"),
            _SETTLE,
            _snap("after"),
            _UNDO,
            _SETTLE,
            _snap("undone"),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert s["selected"]["selected"] == ["disk"], "контроль: клик выбрал disk"
    assert _names(_state(s["after"])) == ["letter", "disk"], f"«Выше»: {s['after']['layers']!r}"
    assert s["after"]["rows"] == ["letter", "disk"]
    assert s["after"]["selected"] == ["disk"], f"выбор идёт за слоем: {s['after']['selected']!r}"
    assert s["after"]["layoutCount"] == s["selected"]["layoutCount"] + 1
    assert [_names(r["preset"]["layers"]) for r in stand.layout_requests()].count(["letter", "disk"]) == 1, (
        f"ровно один запрос раскладки с новым порядком: {stand.layout_requests()!r}"
    )
    assert _state(s["undone"]) == initial


def test_c6_down_moves_toward_start_and_selection_follows(start_pult) -> None:
    """C6 зеркально: `[disk, letter]`, выбран letter, «Ниже» -> `[letter, disk]`, выбран по-прежнему letter."""
    initial = [_DISK, _LETTER]
    stand = _stand(start_pult, initial)
    out = _run_canvas(
        stand.port,
        [
            _READY3,
            _click(_AT_LETTER),
            _snap("selected"),
            _btn("btnLayerDown"),
            _SETTLE,
            _snap("after"),
            _UNDO,
            _SETTLE,
            _snap("undone"),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert s["selected"]["selected"] == ["letter"], "контроль: клик выбрал letter"
    assert _names(_state(s["after"])) == ["letter", "disk"], f"«Ниже»: {s['after']['layers']!r}"
    assert s["after"]["selected"] == ["letter"], f"выбор идёт за слоем: {s['after']['selected']!r}"
    assert s["after"]["layoutCount"] == s["selected"]["layoutCount"] + 1
    assert _state(s["undone"]) == initial


def test_c6_up_on_top_and_down_on_bottom_are_noops(start_pult) -> None:
    """C6: «Выше» у верхнего и «Ниже» у нижнего — ни запроса раскладки, ни записи «Отмена». Запись измеряется
    цепочкой: своя запись (правка поля) -> два no-op -> контрольная операция «Ниже» на верхнем слое (она РАБОТАЕТ);
    первая «Отмена» -> состояние до контроля, вторая -> исходное (лишняя запись no-op сдвинула бы её)."""
    initial = [_DISK, _LETTER]
    stand = _stand(start_pult, initial)
    out = _run_canvas(
        stand.port,
        [
            _READY3,
            {"op": "set_field", "id": "layer0_offset_x", "value": 5},
            _snap("pre"),
            _click(_AT_LETTER),
            _btn("btnLayerUp"),
            _SETTLE,
            _snap("up_top"),
            _click(_AT_DISK),
            _btn("btnLayerDown"),
            _SETTLE,
            _snap("down_bottom"),
            _click(_AT_LETTER),
            _btn("btnLayerDown"),
            _SETTLE,
            _snap("control"),
            _UNDO,
            _snap("u1"),
            _UNDO,
            _snap("u2"),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    pre = _eff(s["pre"])
    assert pre[0]["offset_px"] == [5, 0], "контроль: правка поля видна в форме"
    assert s["up_top"]["selected"] == ["letter"] and s["down_bottom"]["selected"] == ["disk"], "контроль: выбор"
    assert _eff(s["up_top"]) == pre and _eff(s["down_bottom"]) == pre, "no-op не меняет состав"
    assert s["up_top"]["layoutCount"] == s["pre"]["layoutCount"], "«Выше» у верхнего: запроса раскладки нет"
    assert s["down_bottom"]["layoutCount"] == s["pre"]["layoutCount"], "«Ниже» у нижнего: запроса раскладки нет"
    assert _names(_eff(s["control"])) == ["letter", "disk"], (
        f"положительный контроль: «Ниже» на верхнем слое работает: {s['control']['layers']!r}"
    )
    assert _eff(s["u1"]) == pre, "1-я «Отмена» откатывает ТОЛЬКО контрольную операцию"
    assert _eff(s["u2"]) == initial, (
        f"2-я «Отмена» откатывает правку поля (no-op записей не оставили): {s['u2']['layers']!r}"
    )


# --------------------------------------------------------------------------- #
# C7 — «Заменить картинку»                                                    #
# --------------------------------------------------------------------------- #
def test_c7_replace_changes_only_sprite_source(start_pult) -> None:
    """C7: у выбранного слоя изменился ТОЛЬКО `sprite_source` (остальные поля disk — неумолчательные — те же),
    соседи не тронуты; ровно один запрос раскладки с новым источником; «Отмена» возвращает прежний."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            _click(_AT_DISK),
            _snap("selected"),
            _pick(_C),
            _btn("btnLayerSprite"),
            _SETTLE,
            _snap("after"),
            _UNDO,
            _SETTLE,
            _snap("undone"),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert s["selected"]["selected"] == ["disk"], "контроль: клик выбрал disk"
    assert _state(s["after"]) == [{**_DISK, "sprite_source": _C}, _LETTER, _CAP], f"состав: {s['after']['layers']!r}"
    assert s["after"]["selected"] == ["disk"], f"слой остался выбранным: {s['after']['selected']!r}"
    assert s["after"]["layoutCount"] == s["selected"]["layoutCount"] + 1, "ровно один запрос раскладки"
    with_c = [r for r in stand.layout_requests() if r["preset"]["layers"][0]["sprite_source"] == _C]
    assert len(with_c) == 1, f"ровно один запрос раскладки несёт новый источник disk=c.png: {stand.layout_requests()!r}"
    assert _state(s["undone"]) == _INITIAL, f"«Отмена» вернула прежний sprite_source: {s['undone']['layers']!r}"


# --------------------------------------------------------------------------- #
# C8 — без выбранного слоя кнопки ничего не делают                            #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "button, control_at, control_check",
    [
        pytest.param("btnLayerDelete", _AT_LETTER, lambda ly: _names(ly) == ["disk", "cap"], id="delete"),
        pytest.param("btnLayerUp", _AT_DISK, lambda ly: _names(ly) == ["letter", "disk", "cap"], id="up"),
        pytest.param("btnLayerDown", _AT_CAP, lambda ly: _names(ly) == ["disk", "cap", "letter"], id="down"),
        pytest.param("btnLayerSprite", _AT_DISK, lambda ly: ly[0]["sprite_source"] == _C, id="replace"),
    ],
)
def test_c8_no_selection_buttons_do_nothing_but_work_with_selection(
    start_pult, button: str, control_at: list[float], control_check: Callable[[list[dict]], bool]
) -> None:
    """C8: без выбранного слоя (свежая страница) кнопка — ни изменения, ни запроса раскладки, ни записи «Отмена».
    Положительный контроль: та же кнопка при выбранном слое РАБОТАЕТ. Запись измеряется цепочкой (своя запись
    правки поля -> no-op -> контроль -> «Отмена» x2)."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            {"op": "sleep", "ms": 300},
            _pick(_C),
            {"op": "set_field", "id": "layer0_offset_x", "value": 5},
            _snap("pre"),
            _btn(button),
            _SETTLE,
            _snap("noop"),
            _click(control_at),
            _btn(button),
            _SETTLE,
            _snap("control"),
            _UNDO,
            _snap("u1"),
            _UNDO,
            _snap("u2"),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    pre = _eff(s["pre"])
    assert s["pre"]["selected"] == [], f"контроль: слой не выбран: {s['pre']['selected']!r}"
    assert pre[0]["offset_px"] == [5, 0]
    assert _eff(s["noop"]) == pre, f"{button} без выбранного слоя ничего не меняет: {s['noop']['form']!r}"
    assert s["noop"]["layoutCount"] == s["pre"]["layoutCount"], f"{button} без выбранного слоя: запроса раскладки нет"
    assert control_check(_eff(s["control"])), (
        f"положительный контроль: {button} при выбранном слое обязан подействовать: {s['control']['layers']!r}"
    )
    assert _eff(s["u1"]) == pre, "1-я «Отмена» откатывает ТОЛЬКО контрольную операцию"
    assert _eff(s["u2"]) == _INITIAL, (
        f"2-я «Отмена» откатывает правку поля (no-op записей не оставил): {s['u2']['layers']!r}"
    )


# --------------------------------------------------------------------------- #
# Одна операция = одна запись «Отмена» (цепочка разных операций)              #
# --------------------------------------------------------------------------- #
def test_each_operation_is_exactly_one_undo_record(start_pult) -> None:
    """Добавить -> Ниже -> Заменить -> Удалить, затем пять «Отмен»: состояния возвращаются по шагам s3, s2, s1, s0,
    пятая «Отмена» ничего не меняет. Двойная запись любой операции сломала бы эту цепочку (та же операция дважды
    в стеке = лишняя «Отмена» вернула бы прежнее состояние, а не предыдущее)."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            _pick(_A),
            _btn("btnLayerAdd"),
            _SETTLE,
            _snap("s1"),
            _btn("btnLayerDown"),
            _SETTLE,
            _snap("s2"),
            _pick(_C),
            _btn("btnLayerSprite"),
            _SETTLE,
            _snap("s3"),
            _btn("btnLayerDelete"),
            _SETTLE,
            _snap("s4"),
            _UNDO,
            _snap("u1"),
            _UNDO,
            _snap("u2"),
            _UNDO,
            _snap("u3"),
            _UNDO,
            _snap("u4"),
            _UNDO,
            _snap("u5"),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    s1 = [*_INITIAL, _added("a", _A)]
    s2 = [_DISK, _LETTER, _added("a", _A), _CAP]
    s3 = [_DISK, _LETTER, {**_added("a", _A), "sprite_source": _C}, _CAP]
    s4 = [_DISK, _LETTER, _CAP]
    assert [_state(s[t]) for t in ("s1", "s2", "s3", "s4")] == [s1, s2, s3, s4], (
        f"цепочка операций: {[s[t]['layers'] for t in ('s1', 's2', 's3', 's4')]!r}"
    )
    assert [_state(s[t]) for t in ("u1", "u2", "u3", "u4", "u5")] == [s3, s2, s1, _INITIAL, _INITIAL], (
        f"«Отмены» по шагам: {[s[t]['layers'] for t in ('u1', 'u2', 'u3', 'u4', 'u5')]!r}"
    )


# --------------------------------------------------------------------------- #
# C9 — паритет 1.2h: «Сохранить» после операций                               #
# --------------------------------------------------------------------------- #
#: Добавить a; выбрать letter -> Удалить; выбрать cap -> Выше. Итог: [disk, a, cap].
_EDIT_STEPS = [
    _READY,
    _pick(_A),
    _btn("btnLayerAdd"),
    _SETTLE,
    _click(_AT_LETTER),
    _btn("btnLayerDelete"),
    _SETTLE,
    _click(_AT_CAP),
    _btn("btnLayerUp"),
    _SETTLE,
]
_FINAL = [_DISK, _added("a", _A), _CAP]


def test_c9_save_carries_resulting_layers_and_base_rev(start_pult) -> None:
    """C9: добавление + удаление + перестановка, «Сохранить» -> ровно один `preset.commit` с `{preset, base_rev}`:
    `preset.layers` — итоговый список, `base_rev == "rev-1"` (из `get`); ревизия на экране обновилась."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port, [*_EDIT_STEPS, _snap("edited"), _btn("btnPresetSave"), {"op": "sleep", "ms": 300}, _snap("saved")]
    )
    _assert_ran(out)
    assert _state(out["snaps"]["edited"]) == _FINAL, f"итог правок до «Сохранить»: {out['snaps']['edited']['layers']!r}"
    commits = stand.commits()
    assert len(commits) == 1, f"ожидался один preset.commit: {commits!r}"
    assert set(commits[0]) == {"preset", "base_rev"}, f"тело commit как в 1.2h: {sorted(commits[0])!r}"
    assert commits[0]["base_rev"] == "rev-1"
    assert commits[0]["preset"] == {"layers": _FINAL}, f"commit несёт итоговый список слоёв: {commits[0]!r}"
    assert "rev-2" in out["snaps"]["saved"]["rev"], (
        f"после успеха показана новая ревизия: {out['snaps']['saved']['rev']!r}"
    )


def test_c9_conflict_keeps_edit_and_retry_uses_current_rev(start_pult) -> None:
    """C9: `conflict` -> HTTP 409, правка на экране цела (слои, строки формы), повтор уходит с `current_rev`
    и тем же составом."""
    conflict = {"status": "error", "code": "conflict", "current_rev": "rev-9", "message": "пресет изменён параллельно"}
    stand = _stand(start_pult, _INITIAL, commit_replies=[conflict])
    out = _run_canvas(
        stand.port,
        [
            *_EDIT_STEPS,
            _btn("btnPresetSave"),
            {"op": "sleep", "ms": 300},
            _snap("after_conflict"),
            _btn("btnPresetSave"),
            {"op": "sleep", "ms": 300},
        ],
    )
    _assert_ran(out)
    commits = stand.commits()
    assert len(commits) == 2, f"ожидались conflict-commit и повтор: {commits!r}"
    assert [c["base_rev"] for c in commits] == ["rev-1", "rev-9"], f"{commits!r}"
    assert [c["preset"] for c in commits] == [{"layers": _FINAL}] * 2, f"оба commit несут итоговый список: {commits!r}"
    assert _state(out["snaps"]["after_conflict"]) == _FINAL, "после conflict правка на экране цела"
    assert out["snaps"]["after_conflict"]["rows"] == ["disk", "a", "cap"]
    statuses = [e["status"] for e in out["fetchLog"] if e["path"] == "/api/preset/commit"]
    assert statuses == [409, 200], f"conflict -> HTTP 409, повтор -> 200: {statuses!r}"


# --------------------------------------------------------------------------- #
# C10 — отказы: раскладки после «Добавить» и самого списка                    #
# --------------------------------------------------------------------------- #
def test_c10_layout_refusal_after_add_is_visible_and_layer_stays(start_pult) -> None:
    """C10: «Добавить» не-RGBA файл -> раскладка отвечает `invalid`: текст отказа виден в #presetLayoutError,
    слой в presetState остался (и в форме), «Отмена» его убирает."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            {"op": "sleep", "ms": 300},
            _snap("before"),
            _pick(_NOT_RGBA),
            _btn("btnLayerAdd"),
            _SETTLE,
            _snap("refused"),
            _UNDO,
            _SETTLE,
            _snap("undone"),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert s["before"]["error"].strip() == "", f"контроль: до отказа текста нет: {s['before']['error']!r}"
    assert s["refused"]["error"].strip() != "", (
        "отказ раскладки (invalid) должен быть виден текстом в #presetLayoutError"
    )
    assert _state(s["refused"]) == [*_INITIAL, _added("notrgba", _NOT_RGBA)], (
        f"слой остался в presetState после отказа раскладки: {s['refused']['layers']!r}"
    )
    assert s["refused"]["rows"] == ["disk", "letter", "cap", "notrgba"]
    assert _state(s["undone"]) == _INITIAL, f"«Отмена» убирает добавленный слой: {s['undone']['layers']!r}"


def test_c10_sprites_list_refusal_visible_and_editor_still_works(start_pult) -> None:
    """C10: отказ списка (`io_error`) -> текст отказа в #presetSpritesError; форма, канва и «Сохранить» работают
    (правка поля уходит в commit), текст раскладки пуст."""
    refusal = {"status": "error", "code": "io_error", "message": "каталога нет: data/line_sim"}
    stand = _stand(start_pult, _INITIAL, sprites_replies=[refusal])
    out = _run_canvas(
        stand.port,
        [
            _READY,
            {"op": "sleep", "ms": 400},
            _snap("refused"),
            {"op": "set_field", "id": "layer0_offset_x", "value": 5},
            _btn("btnPresetSave"),
            {"op": "sleep", "ms": 300},
        ],
    )
    _assert_ran(out)
    s = out["snaps"]["refused"]
    assert s["spritesError"].strip() != "", "отказ списка должен быть виден текстом в #presetSpritesError"
    assert "data/line_sim" in s["spritesError"], f"текст отказа = сообщение бэкенда: {s['spritesError']!r}"
    assert s["rows"] == ["disk", "letter", "cap"], f"форма собрана несмотря на отказ списка: {s['rows']!r}"
    assert s["error"].strip() == "", f"раскладка работает (канва нарисована): {s['error']!r}"
    commits = stand.commits()
    assert len(commits) == 1 and commits[0]["preset"]["layers"][0]["offset_px"] == [5, 0], (
        f"«Сохранить» работает при отказавшем списке: {commits!r}"
    )


# --------------------------------------------------------------------------- #
# Самопроверки харнесса и фикстуры — ЗЕЛЁНЫЕ уже сейчас, страницу не трогают  #
# --------------------------------------------------------------------------- #
def test_harness_selfcheck_select_model(start_pult) -> None:
    """ЗЕЛЁНЫЙ: модель `<select>`/`<option>` харнесса ведёт себя как описано в `attachSelect` (первый пункт выбран
    сам, value/selectedIndex, неизвестное значение снимает выбор, option.value = textContent без значения,
    очистка сбрасывает выбор, option.selected). Без этого тесты со списком проверяли бы фикцию."""
    out = _run(start_pult(), "select_selfcheck", {})
    assert out["tag"] == "SELECT"
    assert out["empty"] == ["", -1, 0], out["empty"]
    assert out["auto_first"] == ["v1", 0, 3], out["auto_first"]
    assert out["set_v2"] == ["v2", 1], out["set_v2"]
    assert out["set_unknown"] == ["", -1], out["set_unknown"]
    assert out["text_fallback"] == ["only-text", 2], out["text_fallback"]
    assert out["cleared"] == ["", -1, 0], out["cleared"]
    assert out["after_clear"] == ["w1", 0], out["after_clear"]
    assert out["pre_selected"] == ["w2", 1], out["pre_selected"]


def test_selfcheck_fixture_click_points_select_expected_layers(start_pult) -> None:
    """ЗЕЛЁНЫЙ: на нынешней странице (1.3h-b) точки клика фикстуры выбирают именно disk / letter / cap, а клик по
    одному лишь `base` ничего не выбирает, и спрайты всех четырёх слоёв нарисованы. Значит красные тесты выше
    падают из-за отсутствующей разметки/поведения, а не из-за геометрии фикстуры."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            _click(_AT_DISK),
            _snap("disk"),
            _click(_AT_LETTER),
            _snap("letter"),
            _click(_AT_CAP),
            _snap("cap"),
            _click([-95, 95]),
            _snap("base_only"),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert [s[t]["selected"] for t in ("disk", "letter", "cap", "base_only")] == [["disk"], ["letter"], ["cap"], []], (
        f"выбор по точкам фикстуры: {[s[t]['selected'] for t in ('disk', 'letter', 'cap', 'base_only')]!r}"
    )
