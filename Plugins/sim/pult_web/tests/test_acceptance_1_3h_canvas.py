# -*- coding: utf-8 -*-
"""RED-приёмка Task 1.3h-b — канва мышью в редакторе слоёв на `pult_web` (до реализации).

Независимый tester, worktree `ls-13hb-tester`, коммит `f1862c99` (1.3h-a закрыта, 1.3h-b не начата).
Источник — раздел «Task 1.3h» плана `plans/line-sim-layer-editor/phase-1-canvas-html.md` (критерии 3-7; критерии 1-2,
порядок/центры/повёрнутый размер/детерминизм раскладки, закрыты тестами 1.3h-a и здесь не
повторяются). Реализации 1.3h-b в дереве нет. Прочитано ДЛЯ КОНТЕКСТА: `_PRESET_SECTION` /
`_PRESET_SCRIPT` (форма 1.2h, `post()`, id полей), маршрут `/api/preset/layout` и форма ответа
`preset.layout` (1.3h-a, включая `origin_px`), `page_offline.mjs`, тесты 1.2h / 1.3h-a (образцы двойников).

Страница — НАСТОЯЩИЙ `<script>` пульта, прогнанный `page_offline.mjs` (node:vm) против живого сервера
плагина с двойниками процессов. Харнесс расширен: программный 2D-контекст (drawImage / getImageData /
clearRect с матрицей translate/scale/rotate), `new Image()` с настоящей декодировкой PNG, указатель и
клавиатура через `fire(t, ev)`, журнал fetch страницы, шаговый сценарий `canvas_script`. Заглушка
`getImageData` отвечает пикселями, реально нарисованными в холст (самопроверка — последний тест файла,
он ЗЕЛЁНЫЙ уже сейчас), поэтому выбор по альфе и выбор по bbox дают в тестах РАЗНЫЕ ответы.

Контракт для реализации (страница пинит ТОЛЬКО это; всё остальное — дело реализации)
====================================================================================
1. Разметка (в `_PRESET_SECTION`, один блок `<script>` в странице, как сейчас):
   `<canvas id="presetCanvas">`; `<input id="presetZoom" type="number" value="100">` (масштаб в
   ПРОЦЕНТАХ); элемент `id="presetLayoutError"` — пустой `textContent` при успешной раскладке,
   непустой при отказе `preset.layout` (пишется через `textContent`, не `innerHTML`).
2. Раскладка. Страница шлёт `POST /api/preset/layout` с телом, где `preset` — ТЕКУЩЕЕ состояние
   правки (`presetState`/поля формы, не то, что на диске): при загрузке пресета и один раз после
   каждого отпускания жеста. Ответ 1.3h-a: `{status, canvas_px, layers: [{name, png_b64, center_px,
   size_px, origin_px}]}` в порядке снизу вверх. Слой рисуется так: `img = new Image()`;
   `img.src = "data:image/png;base64," + png_b64` (другие источники харнесс не декодирует);
   `ctx.drawImage(img, ...)` прямо в 2D-контекст `#presetCanvas`; слой ставится левым верхним углом
   в `origin_px` (не пересчитывается из `center_px`).
3. Геометрия. `canvas.width/height` страница читает как размер канвы в пикселях (CSS px == пиксели
   битмапа, devicePixelRatio == 1). При 100 % и нетронутой панораме центр объекта (`canvas_px / 2`)
   лежит в центре канвы `(width/2, height/2)`, 1 px объекта == 1 px канвы. Масштаб Z % — вокруг центра
   канвы: 1 px объекта == Z/100 px канвы. Ось Y вниз. Слой без пары в пресете (авто-слой `base`)
   рисуется, но не редактируется; слои пресета сопоставляются с раскладкой по `name`.
4. Масштаб задаётся так: `presetZoom.value = "<проценты>"` и события `input` и `change` на этом поле.
5. Указатель — события `pointerdown` / `pointermove` / `pointerup` на самом `#presetCanvas`.
   Координата — `e.offsetX / e.offsetY` в пикселях канвы (харнесс даёт и `clientX/Y`, `pageX/Y`,
   `x/y` теми же числами; `getBoundingClientRect()` == `{left: 0, top: 0}`); также `e.button`
   (0 — левая), `e.buttons`, `e.pointerId`. `pointerdown` на пикселе слоя, непрозрачном по альфе
   (выбор — верхний слой с `alpha > 0` под курсором, через `getImageData`; прозрачный пиксель верхнего
   слоя -> слой под ним), выбирает слой и начинает жест. Жест `pointerdown -> pointermove* ->
   pointerup`: на `pointerup` `offset_px` слоя += (экранная дельта / (Z/100)), поля формы
   `layer{i}_offset_x/_y` показывают новое значение, в стек «Отмена» кладётся РОВНО одна запись на
   жест (не по записи на `pointermove`; и не по флагу `presetDirty` 1.2h — тот кладёт снимок лишь на
   ПЕРВУЮ правку после сохранения, здесь нужна запись на каждый жест), уходит ровно один
   `POST /api/preset/layout`. Пока кнопка зажата, раскладка НЕ запрашивается. Клик без движения
   (`pointerdown` + `pointerup` в одной точке) выбирает слой и ничего не меняет.
6. Выбор. Строка формы выбранного слоя (`div` внутри `#presetLayers`; первый потомок — `<b>` с
   именем слоя, как в 1.2h) получает токен `selected` в `className` (либо через `classList`);
   выбрана ровно одна строка.
7. Клавиатура. `keydown` на `document`; `e.key` — `ArrowLeft/Right/Up/Down`, `e.shiftKey`. Выбранный
   слой сдвигается в `offset_px` на 1 px (с Shift — на 10 px), `ArrowDown` = `+y`; ровно одна запись
   «Отмена» на нажатие. Масштаб на шаг не влияет.
8. Форма 1.2h как есть: поля `layer{i}_offset_x/_y` (i — индекс в `presetState.layers`, НЕ в
   раскладке: `base` сдвигает индексы), кнопки `btnPresetUndo`, `btnPresetSave`; «Сохранить» шлёт
   `{preset, base_rev}` как в 1.2h; конфликт (HTTP 409) не теряет правку и запоминает `current_rev`.
9. Отказ `preset.layout` (HTTP 400 `invalid`, 504 на таймаут) -> непустой текст в
   `#presetLayoutError`; `presetState`, поля формы и запись «Отмена» от жеста остаются (в следующий
   commit правка попадает).
Не пинится (нет ограничений): ручки поворота/масштаба (геометрия ручек — дело реализации; критерий
плана про `angle_deg`/`scale` мышью этим файлом НЕ покрыт), колесо и панорама, рамка выбора, размер
канвы, порядок запросов раскладки при стрелках.

Харнесс-факты (что реализация получает в тестах): `requestAnimationFrame` == `setTimeout(16)`;
доступны `setTimeout`, `Image`, `atob/btoa`, `Math`, `Promise`, `JSON`; методы рисования кроме
drawImage/clearRect/getImageData/putImageData/createImageData — пустышки; холсты из
`document.createElement("canvas")` — такие же программные (для попиксельного hit-test).
"""

from __future__ import annotations

import base64
import json
import shutil
import socket
import struct
import subprocess
import zlib
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
# Фикстура слоёв: канва объекта 200x200, центр (100, 100)                     #
# --------------------------------------------------------------------------- #
_CANVAS_PX = 200
_OX = "layer0_offset_x"
_OY = "layer0_offset_y"


def _png(w: int, h: int, pixel: Callable[[int, int], tuple[int, int, int, int]]) -> bytes:
    """RGBA PNG без внешних зависимостей (фильтр 0 на каждой строке)."""
    raw = b"".join(b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(w)) for y in range(h))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def _ring(x: int, y: int) -> tuple[int, int, int, int]:
    """60x60: непрозрачна только рамка 10 px, середина 40x40 прозрачна по альфе."""
    inside_hole = 10 <= x < 50 and 10 <= y < 50
    return (0, 0, 0, 0) if inside_hole else (30, 30, 220, 255)


#: имя -> (ширина, высота, PNG). base — авто-слой ленты (в пресете его нет), на всю канву.
_SPRITES: dict[str, tuple[int, int, bytes]] = {
    "base": (200, 200, _png(200, 200, lambda x, y: (90, 90, 90, 255))),
    "cap": (40, 40, _png(40, 40, lambda x, y: (220, 30, 30, 255))),
    "label": (60, 60, _png(60, 60, _ring)),
}


def _data_url(name: str) -> str:
    return "data:image/png;base64," + base64.b64encode(_SPRITES[name][2]).decode("ascii")


def _layer(name: str, ox: int = 0, oy: int = 0) -> dict:
    return {"name": name, "mode": "static", "offset_px": [ox, oy], "angle_deg": 0.0, "scale": 1.0}


def _layout_reply(preset_layers: list[dict]) -> dict:
    """Ответ `preset.layout` для данных слоёв пресета: `base` + слои пресета по порядку.
    Геометрия — формулы 1.3h-a: `origin = round(canvas/2 + offset - size/2)`."""
    layers = []
    for name, ox, oy in [("base", 0, 0)] + [(s["name"], *s["offset_px"]) for s in preset_layers]:
        w, h, _png_bytes = _SPRITES[name]
        layers.append(
            {
                "name": name,
                "png_b64": _data_url(name).split(",", 1)[1],
                "center_px": [ox, oy],
                "size_px": [w, h],
                "origin_px": [round(_CANVAS_PX / 2 + ox - w / 2), round(_CANVAS_PX / 2 + oy - h / 2)],
            }
        )
    return {"status": "ok", "class_name": "A", "canvas_px": [_CANVAS_PX, _CANVAS_PX], "layers": layers}


def _screen(obj_xy: tuple[float, float], zoom_pct: int = 100) -> list[float]:
    """Точка объекта -> смещение от центра канвы в экранных px (контракт п.3)."""
    return [(obj_xy[0] - _CANVAS_PX / 2) * zoom_pct / 100, (obj_xy[1] - _CANVAS_PX / 2) * zoom_pct / 100]


# --------------------------------------------------------------------------- #
# Двойники процессов и стенд                                                  #
# --------------------------------------------------------------------------- #
class _FakeDeviceHubClient:
    """Двойник `DeviceHubClient` (копия техники 1.2h/1.3h-a): `handlers[cmd](args) -> reply` для
    состояния (раскладка зависит от присланного пресета), иначе `responses[cmd]`."""

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


def _stand(
    start_pult: Callable[[], int],
    preset_layers: list[dict],
    *,
    layout_fail: tuple[str, int] | None = None,
    commit_replies: list[dict] | None = None,
) -> _Stand:
    """Стенд: `preset.get` отдаёт rev-1 и слои; `preset.layout` считает раскладку из ПРИСЛАННОГО
    пресета (без `preset` в теле — из исходного); `layout_fail=(kind, from_n)` — с `from_n`-го
    запроса отказ (`invalid` -> код 400, `timeout` -> отказ транспорта без `code` -> 504)."""
    port = start_pult()
    scene = _client_for("camera")
    layers = _client_for("layers")
    initial = json.loads(json.dumps(preset_layers))
    scene.responses["preset.get"] = {"status": "ok", "rev": "rev-1", "preset": {"layers": initial}, "engine": True}
    queue = list(commit_replies or [])
    counter = {"rev": 1}

    def commit(args: dict) -> dict:
        if queue:
            return queue.pop(0)
        counter["rev"] += 1
        return {"status": "ok", "rev": f"rev-{counter['rev']}"}

    scene.handlers["preset.commit"] = commit
    seen = {"n": 0}

    def layout(args: dict) -> dict:
        seen["n"] += 1
        if layout_fail is not None and seen["n"] >= layout_fail[1]:
            if layout_fail[0] == "invalid":
                return {"status": "error", "code": "invalid", "message": "нет спрайта слоя"}
            return {"status": "error", "message": "timeout"}
        preset = args.get("preset") or {"layers": initial}
        return _layout_reply(preset["layers"])

    layers.handlers["preset.layout"] = layout
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


def _assert_drawn(out: dict) -> None:
    """Страница обязана нарисовать слои раскладки на #presetCanvas — иначе дальше проверять нечего."""
    assert out["aborted"] is None and all(w["ok"] for w in out["waits"]), (
        "страница не нарисовала слои раскладки на #presetCanvas (drawImage картинки из data:image/png; "
        f"канвы/раскладки в странице нет): ожидания={out['waits']}"
    )


def _xy(snap: dict) -> list[float]:
    return [float(snap["fields"][_OX]), float(snap["fields"][_OY])]


_IDS = [_OX, _OY]
_WAIT2 = {"op": "wait_drawn", "n": 2}


def _snap(tag: str) -> dict:
    return {"op": "snap", "tag": tag, "ids": _IDS}


# --------------------------------------------------------------------------- #
# Критерий 3 — перетаскивание, зум 100 %                                      #
# --------------------------------------------------------------------------- #
def test_drag_zoom100_sets_offset(start_pult) -> None:
    """Жест (+30, -10) канвы при 100 %: offset_px [5,5] -> [35,-5] ±1 и в теле commit, и в поле формы."""
    stand = _stand(start_pult, [_layer("cap", 5, 5)])
    steps = [
        _WAIT2,
        _snap("before"),
        {"op": "drag", "from": _screen((105, 105)), "to": [5 + 30, 5 - 10], "steps": 5},
        {"op": "sleep", "ms": 300},
        _snap("after"),
        {"op": "press_button", "id": "btnPresetSave"},
        {"op": "sleep", "ms": 300},
    ]
    out = _run_canvas(stand.port, steps)

    _assert_drawn(out)
    assert _xy(out["snaps"]["before"]) == [5.0, 5.0], f"до жеста поля должны показывать [5,5]: {out['snaps']['before']}"
    assert _xy(out["snaps"]["after"]) == pytest.approx([35, -5], abs=1), (
        f"жест (+30,-10) при 100 % должен дать offset_px [35,-5]±1 в поле формы: {out['snaps']['after']['fields']}"
    )
    commits = stand.commits()
    assert len(commits) == 1, f"ожидался один preset.commit: {commits!r}"
    assert commits[0]["preset"]["layers"][0]["offset_px"] == pytest.approx([35, -5], abs=1), (
        f"в теле commit offset_px должен быть [35,-5]±1: {commits[0]!r}"
    )


# --------------------------------------------------------------------------- #
# Критерий 3 — зум 200 %: 60 экранных px -> 30                                #
# --------------------------------------------------------------------------- #
def test_drag_zoom200_halves_screen_delta(start_pult) -> None:
    """Зум 200 %: жест на (+60, -20) экранных px даёт (+30, -10) в offset_px (±1)."""
    stand = _stand(start_pult, [_layer("cap", 5, 5)])
    start = _screen((105, 105), 200)
    steps = [
        _WAIT2,
        {"op": "zoom", "pct": 200},
        {"op": "sleep", "ms": 100},
        {"op": "drag", "from": start, "to": [start[0] + 60, start[1] - 20], "steps": 5},
        {"op": "sleep", "ms": 300},
        _snap("after"),
        {"op": "press_button", "id": "btnPresetSave"},
        {"op": "sleep", "ms": 300},
    ]
    out = _run_canvas(stand.port, steps)

    _assert_drawn(out)
    assert _xy(out["snaps"]["after"]) == pytest.approx([35, -5], abs=1), (
        f"при 200 % 60 экранных px должны дать 30±1 (offset_px [35,-5]), поля: {out['snaps']['after']['fields']}"
    )
    commits = stand.commits()
    assert len(commits) == 1 and commits[0]["preset"]["layers"][0]["offset_px"] == pytest.approx([35, -5], abs=1), (
        f"в теле commit ожидалось [35,-5]±1: {commits!r}"
    )


# --------------------------------------------------------------------------- #
# Критерий 4 — один жест = одна запись undo                                   #
# --------------------------------------------------------------------------- #
def test_one_gesture_one_undo(start_pult) -> None:
    """Два жеста (5 и 3 движения мыши) -> «Отмена» откатывает по жесту, не по движению;
    форма показывает восстановленное значение, лишняя «Отмена» ничего не ломает."""
    stand = _stand(start_pult, [_layer("cap", 5, 5)])
    steps = [
        _WAIT2,
        {"op": "drag", "from": _screen((105, 105)), "to": [35, -5], "steps": 5},
        {"op": "sleep", "ms": 300},
        _snap("gesture_a"),
        # старт в перекрытии старого и нового положений колпачка — попадаем независимо от перерисовки
        {"op": "drag", "from": _screen((120, 100)), "to": [40, 20], "steps": 3},
        {"op": "sleep", "ms": 300},
        _snap("gesture_b"),
        {"op": "press_button", "id": "btnPresetUndo"},
        _snap("undo1"),
        {"op": "press_button", "id": "btnPresetUndo"},
        _snap("undo2"),
        {"op": "press_button", "id": "btnPresetUndo"},
        _snap("undo3_extra"),
        {"op": "press_button", "id": "btnPresetSave"},
        {"op": "sleep", "ms": 300},
    ]
    out = _run_canvas(stand.port, steps)
    snaps = out["snaps"]

    _assert_drawn(out)
    assert _xy(snaps["gesture_a"]) == pytest.approx([35, -5], abs=1), f"жест A: {snaps['gesture_a']['fields']}"
    assert _xy(snaps["gesture_b"]) == pytest.approx([55, 15], abs=1), (
        f"жест B (+20,+20 поверх A): {snaps['gesture_b']['fields']}"
    )
    assert snaps["undo1"]["fields"] == snaps["gesture_a"]["fields"], (
        "одна «Отмена» после двух жестов должна вернуть состояние после жеста A "
        f"(запись на жест, не на движение мыши): {snaps['undo1']['fields']} vs {snaps['gesture_a']['fields']}"
    )
    assert _xy(snaps["undo2"]) == [5.0, 5.0], f"вторая «Отмена» -> исходное [5,5]: {snaps['undo2']['fields']}"
    assert _xy(snaps["undo3_extra"]) == [5.0, 5.0], (
        f"«Отмена» на пустом стеке ничего не меняет: {snaps['undo3_extra']['fields']}"
    )
    commits = stand.commits()
    assert len(commits) == 1 and commits[0]["preset"]["layers"][0]["offset_px"] == [5, 5], (
        f"после отмены всех жестов commit несёт исходное [5,5]: {commits!r}"
    )


# --------------------------------------------------------------------------- #
# Критерий 5 — выбор по альфе, подсветка строки                               #
# --------------------------------------------------------------------------- #
def test_click_transparent_top_selects_below(start_pult) -> None:
    """Клик в прозрачную дырку верхнего слоя `label` выбирает `cap` под ним (по bbox выбрался бы
    `label`); клик по рамке `label` выбирает `label`. Подсвечена ровно строка выбранного слоя."""
    stand = _stand(start_pult, [_layer("cap"), _layer("label")])
    steps = [
        {"op": "wait_drawn", "n": 3},
        {"op": "click", "at": _screen((75, 100))},  # рамка label (слева), cap здесь нет
        {"op": "sleep", "ms": 60},
        {"op": "snap", "tag": "ring", "ids": []},
        {"op": "click", "at": _screen((100, 100))},  # дырка label поверх cap
        {"op": "sleep", "ms": 60},
        {"op": "snap", "tag": "hole", "ids": []},
    ]
    out = _run_canvas(stand.port, steps)
    snaps = out["snaps"]

    _assert_drawn(out)
    assert snaps["ring"]["selected"] == ["label"], (
        f"клик по непрозрачной рамке верхнего слоя должен выбрать label: {snaps['ring']['selected']!r}"
    )
    assert snaps["hole"]["selected"] == ["cap"], (
        "клик в прозрачную дырку label должен выбрать cap под ним (выбор по альфе, не по bbox): "
        f"{snaps['hole']['selected']!r}"
    )


# --------------------------------------------------------------------------- #
# Критерий 6 — отказ layout виден, правка не теряется                         #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "kind, fail_from",
    [
        pytest.param("invalid", 2, id="invalid_after_release"),
        pytest.param("timeout", 2, id="timeout_after_release"),
        pytest.param("invalid", 1, id="invalid_first_request"),
        pytest.param("timeout", 1, id="timeout_first_request"),
    ],
)
def test_layout_invalid_and_timeout_visible_and_edit_kept(start_pult, kind: str, fail_from: int) -> None:
    """Отказ `preset.layout` (invalid -> 400, таймаут -> 504): непустой текст в #presetLayoutError
    (до отказа он пуст); правка мышью (или полем, если отказал первый запрос) остаётся и уходит в commit."""
    stand = _stand(start_pult, [_layer("cap", 5, 5)], layout_fail=(kind, fail_from))
    if fail_from == 2:
        steps: list[dict] = [
            _WAIT2,
            {"op": "snap", "tag": "ok_state", "ids": _IDS},
            {"op": "drag", "from": _screen((105, 105)), "to": [35, -5], "steps": 4},
            {"op": "sleep", "ms": 400},
            _snap("after"),
            {"op": "press_button", "id": "btnPresetSave"},
            {"op": "sleep", "ms": 300},
        ]
        expected = [35, -5]
    else:
        steps = [
            {"op": "sleep", "ms": 500},
            _snap("after"),
            {"op": "set_field", "id": _OX, "value": 15},
            {"op": "press_button", "id": "btnPresetSave"},
            {"op": "sleep", "ms": 300},
        ]
        expected = [15, 5]
    out = _run_canvas(stand.port, steps)
    snaps = out["snaps"]

    if fail_from == 2:
        _assert_drawn(out)
        assert snaps["ok_state"]["error"].strip() == "", (
            f"контроль: при успешной раскладке #presetLayoutError пуст: {snaps['ok_state']['error']!r}"
        )
        assert len(stand.layout_requests()) >= 2, (
            "после отпускания жеста ожидался повторный запрос раскладки (он и должен отказать): "
            f"{stand.layout_requests()!r}"
        )
        assert _xy(snaps["after"]) == pytest.approx(expected, abs=1), (
            f"отказ раскладки не должен терять правку: поля {snaps['after']['fields']}"
        )
    assert snaps["after"]["error"].strip() != "", (
        f"отказ preset.layout ({kind}, с запроса №{fail_from}) должен быть виден текстом в #presetLayoutError"
    )
    commits = stand.commits()
    assert len(commits) == 1 and commits[0]["preset"]["layers"][0]["offset_px"] == pytest.approx(expected, abs=1), (
        f"правка должна дойти до commit, несмотря на отказ раскладки: {commits!r}"
    )


# --------------------------------------------------------------------------- #
# Критерий 7 — паритет с 1.2h: base_rev и conflict -> 409                     #
# --------------------------------------------------------------------------- #
def test_commit_parity_base_rev_and_conflict_409(start_pult) -> None:
    """Правка мышью -> «Сохранить»: `{preset, base_rev}`; после успеха следующий commit идёт с новой
    ревизией; `conflict` -> HTTP 409, правка на экране цела, повтор уходит с `current_rev`."""
    # --- часть А: ok-цепочка ревизий
    stand = _stand(start_pult, [_layer("cap", 5, 5)])
    steps = [
        _WAIT2,
        {"op": "drag", "from": _screen((105, 105)), "to": [35, -5], "steps": 4},
        {"op": "sleep", "ms": 300},
        {"op": "press_button", "id": "btnPresetSave"},
        {"op": "sleep", "ms": 300},
        {"op": "snap", "tag": "saved", "ids": _IDS},
        {"op": "drag", "from": _screen((120, 100)), "to": [40, 20], "steps": 3},
        {"op": "sleep", "ms": 300},
        {"op": "press_button", "id": "btnPresetSave"},
        {"op": "sleep", "ms": 300},
    ]
    out = _run_canvas(stand.port, steps)
    _assert_drawn(out)
    commits = stand.commits()
    assert len(commits) == 2, f"ожидались два preset.commit: {commits!r}"
    assert set(commits[0]) == {"preset", "base_rev"}, (
        f"тело commit как в 1.2h — {{preset, base_rev}}: {sorted(commits[0])!r}"
    )
    assert commits[0]["base_rev"] == "rev-1", f"первый commit с base_rev из preset.get: {commits[0]!r}"
    assert commits[0]["preset"]["layers"][0]["offset_px"] == pytest.approx([35, -5], abs=1), f"{commits[0]!r}"
    assert "rev-2" in out["snaps"]["saved"]["rev"], (
        f"после успешного commit показана новая ревизия: {out['snaps']['saved']['rev']!r}"
    )
    assert commits[1]["base_rev"] == "rev-2", f"второй commit — с ревизией из ответа первого: {commits[1]!r}"
    assert commits[1]["preset"]["layers"][0]["offset_px"] == pytest.approx([55, 15], abs=1), f"{commits[1]!r}"
    statuses = [e["status"] for e in out["fetchLog"] if e["path"] == "/api/preset/commit"]
    assert statuses == [200, 200], f"HTTP-статусы двух успешных commit: {statuses!r}"

    # --- часть Б: conflict -> 409, правка цела, повтор с current_rev
    conflict = {"status": "error", "code": "conflict", "current_rev": "rev-9", "message": "пресет изменён параллельно"}
    stand2 = _stand(start_pult, [_layer("cap", 5, 5)], commit_replies=[conflict])
    steps2 = [
        _WAIT2,
        {"op": "drag", "from": _screen((105, 105)), "to": [35, -5], "steps": 4},
        {"op": "sleep", "ms": 300},
        {"op": "press_button", "id": "btnPresetSave"},
        {"op": "sleep", "ms": 300},
        _snap("after_conflict"),
        {"op": "press_button", "id": "btnPresetSave"},
        {"op": "sleep", "ms": 300},
    ]
    out2 = _run_canvas(stand2.port, steps2)
    _assert_drawn(out2)
    commits2 = stand2.commits()
    assert len(commits2) == 2, f"ожидались conflict-commit и повтор: {commits2!r}"
    assert commits2[0]["base_rev"] == "rev-1", f"{commits2[0]!r}"
    assert commits2[1]["base_rev"] == "rev-9", f"повтор должен уйти с current_rev как base_rev: {commits2[1]!r}"
    assert commits2[1]["preset"]["layers"][0]["offset_px"] == pytest.approx([35, -5], abs=1), (
        f"правка мышью не должна теряться при conflict: {commits2[1]!r}"
    )
    assert _xy(out2["snaps"]["after_conflict"]) == pytest.approx([35, -5], abs=1), (
        f"после conflict поле формы всё ещё показывает правку: {out2['snaps']['after_conflict']['fields']}"
    )
    statuses2 = [e["status"] for e in out2["fetchLog"] if e["path"] == "/api/preset/commit"]
    assert statuses2 == [409, 200], f"conflict -> HTTP 409, повтор -> 200 (как в 1.2h): {statuses2!r}"


# --------------------------------------------------------------------------- #
# Клавиатура: стрелки 1 px, Shift 10 px, одна запись undo на нажатие          #
# --------------------------------------------------------------------------- #
def test_arrow_keys_1px_shift_10px_one_undo_each(start_pult) -> None:
    """Выбранный слой: → +1 по x; Shift+↓ +10 по y; ← −1 по x; ↑ −1 по y — по одной записи «Отмена»
    на нажатие (четыре «Отмены» возвращают [5,5] по шагам)."""
    stand = _stand(start_pult, [_layer("cap", 5, 5)])
    steps = [
        _WAIT2,
        {"op": "click", "at": _screen((105, 105))},
        {"op": "sleep", "ms": 60},
        _snap("selected"),
        {"op": "key", "key": "ArrowRight"},
        _snap("k1"),
        {"op": "key", "key": "ArrowDown", "shift": True},
        _snap("k2"),
        {"op": "key", "key": "ArrowLeft"},
        _snap("k3"),
        {"op": "key", "key": "ArrowUp"},
        _snap("k4"),
        {"op": "press_button", "id": "btnPresetUndo"},
        _snap("u1"),
        {"op": "press_button", "id": "btnPresetUndo"},
        _snap("u2"),
        {"op": "press_button", "id": "btnPresetUndo"},
        _snap("u3"),
        {"op": "press_button", "id": "btnPresetUndo"},
        _snap("u4"),
    ]
    out = _run_canvas(stand.port, steps)
    snaps = out["snaps"]

    _assert_drawn(out)
    got = {tag: _xy(snaps[tag]) for tag in ("selected", "k1", "k2", "k3", "k4", "u1", "u2", "u3", "u4")}
    assert got["selected"] == [5.0, 5.0], f"выбор кликом (без движения) ничего не меняет: {got['selected']}"
    assert got["k1"] == [6.0, 5.0], f"→ : +1 по x, получено {got['k1']}"
    assert got["k2"] == [6.0, 15.0], f"Shift+↓ : +10 по y, получено {got['k2']}"
    assert got["k3"] == [5.0, 15.0], f"← : −1 по x, получено {got['k3']}"
    assert got["k4"] == [5.0, 14.0], f"↑ : −1 по y, получено {got['k4']}"
    assert [got["u1"], got["u2"], got["u3"], got["u4"]] == [[5.0, 15.0], [6.0, 15.0], [6.0, 5.0], [5.0, 5.0]], (
        "по одной записи «Отмена» на нажатие — четыре «Отмены» по шагам назад: "
        f"{[got[t] for t in ('u1', 'u2', 'u3', 'u4')]}"
    )


# --------------------------------------------------------------------------- #
# base: виден, но не редактируется                                            #
# --------------------------------------------------------------------------- #
def test_base_layer_visible_not_editable(start_pult) -> None:
    """Авто-слой `base` (есть в раскладке, нет в пресете) рисуется на канве ровно по `origin_px`,
    а жест по нему ничего не меняет (индекс раскладки != индекс пресета: `base` сдвигает их)."""
    stand = _stand(start_pult, [_layer("cap", 5, 5)])
    steps = [
        _WAIT2,
        {"op": "drag", "from": _screen((20, 20)), "to": [-80 + 30, -80 - 10], "steps": 4},  # пиксель только base
        {"op": "sleep", "ms": 300},
        _snap("after_base_drag"),
        {"op": "press_button", "id": "btnPresetUndo"},
        _snap("after_undo"),
        {"op": "press_button", "id": "btnPresetSave"},
        {"op": "sleep", "ms": 300},
    ]
    out = _run_canvas(stand.port, steps)
    snaps = out["snaps"]

    _assert_drawn(out)
    # --- виден: drawImage(base) на основной канве в нужном месте, под cap
    cx, cy = out["canvas"][0] / 2, out["canvas"][1] / 2
    last: dict[str, dict] = {}
    order: dict[str, int] = {}
    for i, entry in enumerate(out["draws"]):
        last[entry["src"]] = entry
        order[entry["src"]] = i
    base_src, cap_src = _data_url("base"), _data_url("cap")
    assert base_src in last, "слой base не нарисован на #presetCanvas — он должен быть виден"
    assert last[base_src]["bbox"] == pytest.approx([cx - 100, cy - 100, cx + 100, cy + 100], abs=1), (
        f"base — origin (0,0), 200x200 при центре канвы ({cx},{cy}): {last[base_src]['bbox']}"
    )
    assert last[cap_src]["bbox"] == pytest.approx([cx - 15, cy - 15, cx + 25, cy + 25], abs=1), (
        f"cap с offset [5,5] — origin (85,85), 40x40: {last[cap_src]['bbox']}"
    )
    assert order[base_src] < order[cap_src], "base рисуется под cap (порядок раскладки снизу вверх)"
    # --- не редактируется
    assert snaps["after_base_drag"]["fields"] == {_OX: "5", _OY: "5"}, (
        f"жест по base не должен менять offset_px слоя пресета: {snaps['after_base_drag']['fields']}"
    )
    assert snaps["after_undo"]["fields"] == {_OX: "5", _OY: "5"}, f"{snaps['after_undo']['fields']}"
    commits = stand.commits()
    assert len(commits) == 1 and commits[0]["preset"]["layers"][0]["offset_px"] == [5, 5], (
        f"после жеста по base слой cap остался на [5,5]: {commits!r}"
    )


# --------------------------------------------------------------------------- #
# Отпускание -> повторный запрос раскладки (и только оно)                     #
# --------------------------------------------------------------------------- #
def test_release_rerequests_layout(start_pult) -> None:
    """Пока кнопка зажата, раскладку не просят; после отпускания — ровно один новый запрос,
    и его тело несёт УЖЕ сдвинутый пресет (offset_px [35,-5]±1)."""
    stand = _stand(start_pult, [_layer("cap", 5, 5)])
    steps = [
        _WAIT2,
        {"op": "sleep", "ms": 250},
        {"op": "snap", "tag": "s0", "ids": []},
        {"op": "press", "at": _screen((105, 105))},
        {"op": "move", "at": [15, 0]},
        {"op": "move", "at": [25, -5]},
        {"op": "move", "at": [35, -5]},
        {"op": "sleep", "ms": 200},
        {"op": "snap", "tag": "held", "ids": []},
        {"op": "release", "at": [35, -5]},
        {"op": "sleep", "ms": 400},
        {"op": "snap", "tag": "s1", "ids": []},
    ]
    out = _run_canvas(stand.port, steps)
    snaps = out["snaps"]

    _assert_drawn(out)
    n0 = snaps["s0"]["layoutCount"]
    assert n0 >= 1, f"до жеста страница должна была запросить раскладку (иначе рисовать нечего): {n0}"
    assert snaps["held"]["layoutCount"] == n0, (
        f"пока кнопка зажата, раскладка не запрашивается: было {n0}, стало {snaps['held']['layoutCount']}"
    )
    assert snaps["s1"]["layoutCount"] == n0 + 1, (
        f"после отпускания — ровно один повторный запрос раскладки: было {n0}, стало {snaps['s1']['layoutCount']}"
    )
    requests = stand.layout_requests()
    assert len(requests) == n0 + 1, (
        f"сервер-двойник видел {len(requests)} запросов, страница слала {n0 + 1}: {requests!r}"
    )
    assert requests[-1].get("preset", {}).get("layers", [{}])[0].get("offset_px") == pytest.approx([35, -5], abs=1), (
        f"повторный запрос должен нести пресет со сдвинутым слоем: {requests[-1]!r}"
    )


# --------------------------------------------------------------------------- #
# Самопроверка заглушек харнесса — ЗЕЛЁНАЯ сейчас, страницу не трогает        #
# --------------------------------------------------------------------------- #
def test_harness_selfcheck_alpha_stub_is_not_always_opaque(start_pult) -> None:
    """Заглушка getImageData отвечает пикселями нарисованного PNG: дырка кольца -> 0, рамка -> 255,
    и это держится при сдвиге (translate) и растяжении (drawImage с размером). Без этого тесты
    выбора по альфе были бы вакуумными (заглушка «всегда непрозрачно» не отличает bbox от альфы)."""
    spec = {
        "ring": {
            "url": _data_url("label"),
            "probes": [[30, 30], [5, 30], [55, 30], [30, 5], [30, 55], [10, 10], [9, 9]],
        },
        "cap": {"url": _data_url("cap"), "probes": [[20, 20], [0, 0], [39, 39]]},
    }
    out = _run(start_pult(), "stub_selfcheck", spec)  # страница не нужна, но харнесс грузит `/` с сервера
    assert out["ring"]["w"] == 60 and out["ring"]["h"] == 60, f"PNG кольца декодирован неверно: {out['ring']}"
    for variant in ("plain", "shifted", "scaled"):
        assert out["ring"][variant] == [0, 255, 255, 255, 255, 0, 255], f"кольцо, {variant}: {out['ring'][variant]}"
        assert out["cap"][variant] == [255, 255, 255], f"колпачок, {variant}: {out['cap'][variant]}"
