# -*- coding: utf-8 -*-
# ruff: noqa: F811 - фикстура start_pult импортирована из приёмки 1.3h-b и принимается тестами по имени
"""RED-приёмка Task 5.3 — инструменты канвы веб-редактора слоёв `pult_web` (до реализации).

Независимый tester (слепой), worktree `lr53-tester`, коммит `fdfb5c1e` (5.3 не начата).
Источник — только «Контракт страницы» п. 1-6 и Acceptance A1-A6 из `plans/layer-render/phase-5-editor.md`
(Task 5.3) плюс докстринг контракта 1.3h-b (`test_acceptance_1_3h_canvas.py`), который действует как есть.
Реализации 5.3 в дереве нет; существующую страницу (`plugin.py`) тестер читал ТОЛЬКО как форму 1.3h-b
(id полей, `presetState`, `collectPresetFromFields`), реализацию 5.3 читать было нечего.

Страница — НАСТОЯЩИЙ `<script>` пульта, прогнанный `page_offline.mjs` (node:vm) против живого сервера
плагина с двойниками процессов (техника 1.3h-b). Харнесс расширен АДДИТИВНО (существующие сценарии не тронуты):
`press_mod`/`click_mod` (указатель с Shift), `key_mod` (ctrl/meta), `toggle` (щелчок по чекбоксу: фокус, checked,
click/input/change, всплытие до #presetLayers для чекбоксов строк), `type_field` (input+change), `pixel`
(RGBA пикселя основной канвы), `snap_ui` (checked, число запросов /api/preset*, разбор строк слоёв).

Модель харнесса, которую тесты ПРИНИМАЮТ НА ВЕРУ
------------------------------------------------
- Чекбоксы строк (`presetVis{i}`/`presetLock{i}`) и поля сетки находятся харнессом по id: сперва среди
  потомков `#presetLayers` (если страница создала их через createElement и назначила id), иначе через реестр
  `document.getElementById` (разметка через innerHTML + привязка по id, как поля слоя в 1.2h).
- Неизвестный id в реестре получает значение "101.1" — поэтому шаг сетки в тестах ВСЕГДА задаётся явно
  (`type_field`); умолчание `value="10"` пинится только разметкой, отданной сервером (тест п. 1).
- Стрелки/горячие клавиши идут `document.fire("keydown", ...)` с `target` = канва по умолчанию.

Геометрия фикстуры (канва объекта 200x200, центр (100,100); холст страницы 640x480, зум 100 %):
  base (авто-слой) 200x200 серый (90,90,90)  — только в раскладке, в пресете его нет;
  plate 60x60 синий,  offset [0,0]   -> объект (70..130)x(70..130),  индекс в presetState.layers = 0
  cap   40x40 красный, offset [20,0]  -> объект (100..140)x(80..120), индекс 1 (поверх plate)
  bolt  40x40 зелёный, offset [-60,-60] -> объект (20..60)x(20..60),  индекс 2 (отдельно от остальных)
Точки клика (объект): PLATE_ONLY (75,100) — только plate; OVERLAP (110,100) — plate под cap;
CAP_ONLY (135,100) — только cap; BOLT (40,40) — только bolt. Индекс `i` в `presetVis{i}`/`layer{i}_offset_*` —
индекс в presetState.layers (base сдвигает индексы раскладки, но не пресета).

Ожидание КРАСНОГО (записано ДО первого прогона)
-----------------------------------------------
Все тесты нового поведения падают на ASSERT о поведении (или на явно названном отсутствующем элементе разметки):
п. 1 — нет id в разметке; п. 2 — смещение не привязано (получим свободное [33,-17]); п. 3 — Shift-клик не даёт
выбор из двух строк (precondition `selected == [cap, bolt]`); п. 4 — Delete/Ctrl+Z/Ctrl+A/Escape/g ничего не
делают; п. 5 — `presetZoom` остаётся "100"; п. 6 — скрытый слой остаётся нарисованным, замок не мешает выбору.
ЗЕЛЁНЫЕ уже сейчас (контроль, не новое поведение): `test_grid_off_keeps_free_offset` (сетка выкл — поведение 1.3h-b),
`test_handles_only_for_single_selection[1]` (одиночный выбор — ручка масштаба работает как в 1.3h-b).
Тесты, где без реализации «ничего не происходит» (тишина сетки, стрелки без привязки, горячие клавиши в поле,
флаги вне тел запросов/«Отмены»), несут ЯКОРЬ существования — шаг, который падает пока функции нет, иначе зелёный
сейчас означал бы «ничего не сделано», а не «сделано верно».
"""

from __future__ import annotations

import base64
import json
import math
import re
import urllib.request
from html.parser import HTMLParser
from typing import Any, Callable

import pytest

from Plugins.sim.pult_web.tests.test_acceptance_1_3h_canvas import (
    _NODE,
    _client_for,
    _png,
    _run,
    start_pult,  # noqa: F401 - фикстура, pytest находит её по имени в модуле
)

# --------------------------------------------------------------------------- #
# Фикстура слоёв                                                              #
# --------------------------------------------------------------------------- #
RED = [220, 30, 30, 255]
BLUE = [30, 30, 220, 255]
GREEN = [30, 200, 30, 255]
GRAY = [90, 90, 90, 255]

_SPRITES: dict[str, tuple[int, int, bytes]] = {
    "base": (200, 200, _png(200, 200, lambda x, y: tuple(GRAY))),
    "plate": (60, 60, _png(60, 60, lambda x, y: tuple(BLUE))),
    "cap": (40, 40, _png(40, 40, lambda x, y: tuple(RED))),
    "bolt": (40, 40, _png(40, 40, lambda x, y: tuple(GREEN))),
}

PLATE_ONLY = (75, 100)
OVERLAP = (110, 100)
CAP_ONLY = (135, 100)
BOLT = (40, 40)
CAP_BR_CORNER = (141, 121)  # на 1 px за правым нижним углом рамки cap: внутри ручки масштаба (±8), вне любого слоя


def _layer(name: str, ox: int, oy: int) -> dict:
    return {"name": name, "mode": "static", "offset_px": [ox, oy], "angle_deg": 0.0, "scale": 1.0}


_PRESET0 = [_layer("plate", 0, 0), _layer("cap", 20, 0), _layer("bolt", -60, -60)]
_INITIAL = [[0, 0], [20, 0], [-60, -60]]


def _layout_reply(preset_layers: list[dict], canvas: tuple[int, int]) -> dict:
    layers = []
    for name, ox, oy in [("base", 0, 0)] + [(s["name"], *s["offset_px"]) for s in preset_layers]:
        w, h, png = _SPRITES[name]
        layers.append(
            {
                "name": name,
                "png_b64": base64.b64encode(png).decode("ascii"),
                "center_px": [ox, oy],
                "size_px": [w, h],
                "origin_px": [round(canvas[0] / 2 + ox - w / 2), round(canvas[1] / 2 + oy - h / 2)],
            }
        )
    return {"status": "ok", "class_name": "A", "canvas_px": list(canvas), "layers": layers}


class _Stand:
    def __init__(self, port: int, scene: Any, layers: Any) -> None:
        self.port = port
        self.scene = scene
        self.layers = layers

    def commits(self) -> list[dict]:
        return [a for c, a in self.scene.calls if c == "preset.commit"]


def _stand(start_pult: Callable[[], int], canvas: tuple[int, int] = (200, 200)) -> _Stand:
    port = start_pult()
    scene, layers = _client_for("camera"), _client_for("layers")
    initial = json.loads(json.dumps(_PRESET0))
    scene.responses["preset.get"] = {"status": "ok", "rev": "rev-1", "preset": {"layers": initial}, "engine": True}
    counter = {"rev": 1}

    def commit(args: dict) -> dict:
        counter["rev"] += 1
        return {"status": "ok", "rev": f"rev-{counter['rev']}"}

    scene.handlers["preset.commit"] = commit
    layers.handlers["preset.layout"] = lambda args: _layout_reply(
        (args.get("preset") or {"layers": initial})["layers"], canvas
    )
    return _Stand(port, scene, layers)


# --------------------------------------------------------------------------- #
# Шаги сценария                                                               #
# --------------------------------------------------------------------------- #
def _F(i: int, axis: str) -> str:
    return f"layer{i}_offset_{axis}"


_IDS = [_F(i, a) for i in range(3) for a in "xy"] + ["presetZoom"]
WAIT = {"op": "wait_drawn", "n": 4}
SETTLE = {"op": "settle"}
# Стрелки просят раскладку отложенно (таймер страницы ~200 мс): `settle` один его не ждёт (тихое окно 150 мс).
QUIET = [{"op": "sleep", "ms": 600}, SETTLE]


def _at(pt: tuple[float, float], zoom_pct: int = 100) -> list[float]:
    """Точка объекта -> смещение от центра канвы в экранных px (канва объекта 200x200)."""
    return [(pt[0] - 100) * zoom_pct / 100, (pt[1] - 100) * zoom_pct / 100]


def _click(pt: tuple[float, float], shift: bool = False) -> dict:
    return {"op": "click_mod", "at": _at(pt), "shift": True} if shift else {"op": "click", "at": _at(pt)}


def _drag(pt: tuple[float, float], dx: float, dy: float) -> dict:
    a = _at(pt)
    return {"op": "drag", "from": a, "to": [a[0] + dx, a[1] + dy], "steps": 5}


def _snap(tag: str) -> dict:
    return {"op": "snap", "tag": tag, "ids": _IDS}


def _ui(tag: str, checked: list[str] | None = None) -> dict:
    return {"op": "snap_ui", "tag": tag, "checked": checked or []}


def _px(tag: str, pt: tuple[float, float]) -> dict:
    return {"op": "pixel", "tag": tag, "at": _at(pt)}


def _toggle(id_: str, checked: bool) -> dict:
    return {"op": "toggle", "id": id_, "checked": checked}


def _key(key: str, **kw: Any) -> dict:
    return {"op": "key", "key": key, **kw}


def _sleep(ms: int) -> dict:
    return {"op": "sleep", "ms": ms}


UNDO = {"op": "press_button", "id": "btnPresetUndo"}
SAVE = {"op": "press_button", "id": "btnPresetSave"}
SELECT_CAP_BOLT = [_click(CAP_ONLY), _click(BOLT, shift=True), _sleep(250)]


def _go(start_pult: Callable[[], int], steps: list[dict], canvas: tuple[int, int] = (200, 200)) -> tuple[_Stand, dict]:
    stand = _stand(start_pult, canvas)
    assert _NODE is not None, "node недоступен в PATH"
    out = _run(stand.port, "canvas_script", steps)
    assert out["aborted"] is None and all(w["ok"] for w in out["waits"]), (
        f"страница не нарисовала слои раскладки (base+3 слоя) на #presetCanvas: {out['waits']}"
    )
    return stand, out


def _offs(out: dict, tag: str, n: int = 3) -> list[list[float]]:
    f = out["snaps"][tag]["fields"]
    return [[float(f[_F(i, "x")]), float(f[_F(i, "y")])] for i in range(n)]


def _sel(out: dict, tag: str) -> list[str]:
    return out["snaps"][tag]["selected"]


def _names(out: dict, tag: str) -> list[str]:
    return [ly["name"] for ly in out["snaps"][tag]["layers"]]


# --------------------------------------------------------------------------- #
# П. 1 — разметка                                                             #
# --------------------------------------------------------------------------- #
class _Tags(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.by_id: dict[str, tuple[str, dict[str, str | None]]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        d = dict(attrs)
        if d.get("id"):
            self.by_id[str(d["id"])] = (tag, d)


def test_p1_static_markup_grid_step_fit(start_pult) -> None:
    """П.1: в отданной странице — `presetGrid` (checkbox, по умолчанию выкл), `presetGridStep`
    (number, value=10, min=1), `btnPresetFit` (button)."""
    port = start_pult()
    html = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10).read().decode("utf-8")
    p = _Tags()
    p.feed(html)
    missing = [i for i in ("presetGrid", "presetGridStep", "btnPresetFit") if i not in p.by_id]
    assert not missing, f"в разметке страницы нет элементов контракта 5.3 п.1: {missing}"
    tag, a = p.by_id["presetGrid"]
    assert (tag, a.get("type")) == ("input", "checkbox"), f"presetGrid должен быть input[type=checkbox]: {tag} {a}"
    assert "checked" not in a, f"сетка по умолчанию выключена, у presetGrid нет атрибута checked: {a}"
    tag, a = p.by_id["presetGridStep"]
    assert (tag, a.get("type"), a.get("value"), a.get("min")) == ("input", "number", "10", "1"), (
        f"presetGridStep: input[type=number] value=10 min=1, получено {tag} {a}"
    )
    assert p.by_id["btnPresetFit"][0] == "button", f"btnPresetFit должен быть <button>: {p.by_id['btnPresetFit']}"


def _control(ui: dict, i: int, kind: str) -> dict:
    """Чекбокс `preset{kind}{i}` ИЗ СТРОКИ i: создан узлом с id или записан в разметку строки."""
    cid = f"preset{kind}{i}"
    row = ui["rowInfo"][i]
    node = next((n for n in row["ids"] if n["id"] == cid), None)
    tag = re.search(rf'<input\b[^>]*\bid="{cid}"[^>]*>', row["markup"])
    found = node is not None or tag is not None
    is_checkbox = (node is not None and node["type"] in (None, "checkbox")) or (
        tag is not None and re.search(r'\btype="checkbox"', tag.group(0)) is not None
    )
    attr_checked = tag is not None and re.search(r"\bchecked\b", tag.group(0)) is not None
    prop_checked = ui["checked"].get(cid, False) or (node is not None and node["checked"])
    return {"id": cid, "found": found, "checkbox": is_checkbox, "checked": bool(prop_checked or attr_checked)}


def test_p1_row_has_vis_and_lock_checkboxes_with_defaults(start_pult) -> None:
    """П.1: в строке КАЖДОГО слоя пресета (i — индекс в presetState.layers) есть чекбоксы `presetVis{i}`
    (по умолчанию отмечен) и `presetLock{i}` (по умолчанию снят)."""
    ids = [f"preset{k}{i}" for i in range(3) for k in ("Vis", "Lock")]
    _stand_, out = _go(start_pult, [WAIT, _ui("u", ids)])
    ui = out["ui"]["u"]
    assert len(ui["rowInfo"]) == 3, f"в #presetLayers ожидалось 3 строки слоёв: {len(ui['rowInfo'])}"
    for i in range(3):
        vis, lock = _control(ui, i, "Vis"), _control(ui, i, "Lock")
        assert vis["found"], (
            f"в строке {i} нет чекбокса presetVis{i} (ни узлом с id, ни в разметке строки): {ui['rowInfo'][i]}"
        )
        assert lock["found"], f"в строке {i} нет чекбокса presetLock{i}: {ui['rowInfo'][i]}"
        assert vis["checkbox"] and lock["checkbox"], (
            f"presetVis{i}/presetLock{i} должны быть type=checkbox: {vis} {lock}"
        )
        assert vis["checked"] is True, f"presetVis{i} по умолчанию отмечен (слой видим): {vis}"
        assert lock["checked"] is False, f"presetLock{i} по умолчанию снят (слой не заперт): {lock}"


# --------------------------------------------------------------------------- #
# П. 2 — привязка к сетке                                                     #
# --------------------------------------------------------------------------- #
def _grid_on(step: int) -> list[dict]:
    return [_toggle("presetGrid", True), {"op": "type_field", "id": "presetGridStep", "value": step}]


@pytest.mark.parametrize(
    "step, expected",
    [
        pytest.param(10, [30, -20], id="step10"),  # сырое [20+13, 0-17] = [33,-17]: 33->30, -17->-20
        pytest.param(25, [25, -25], id="step25"),  # 33/25=1.32->25, -17/25=-0.68->-25
    ],
)
def test_p2_grid_on_snaps_dragged_offset_to_step_multiple(start_pult, step: int, expected: list[int]) -> None:
    """П.2: сетка вкл -> на pointerup offset_px захваченного слоя на каждой оси — ближайшее кратное шагу;
    и в поле формы, и в теле commit."""
    steps = [WAIT, *_grid_on(step), _drag(CAP_ONLY, 13, -17), _sleep(300), _snap("a"), SAVE, SETTLE]
    stand, out = _go(start_pult, steps)
    assert _offs(out, "a")[1] == expected, (
        f"сетка {step} px: ждали привязанное {expected} (сырое было [33,-17]): {out['snaps']['a']['fields']}"
    )
    commits = stand.commits()
    assert len(commits) == 1 and commits[0]["preset"]["layers"][1]["offset_px"] == expected, f"тело commit: {commits!r}"


def test_p2_grid_off_keeps_free_offset(start_pult) -> None:
    """КОНТРОЛЬ (зелёный и сейчас): сетка выкл (по умолчанию) — поведение 1.3h-b, смещение свободное [33,-17]."""
    _stand_, out = _go(start_pult, [WAIT, _drag(CAP_ONLY, 13, -17), _sleep(300), _snap("a")])
    assert _offs(out, "a")[1] == [33, -17], f"сетка выключена: смещение свободное: {out['snaps']['a']['fields']}"


def test_p2_grid_snap_moves_rest_of_selection_by_same_delta(start_pult) -> None:
    """П.2+3: выбраны cap и bolt, тащим cap (+13,-17) при сетке 10: cap [33,-17] -> [30,-20]; bolt сдвигается на
    ТУ ЖЕ дельту (+10,-20), а не привязывается сам: [-60,-60] -> [-50,-80] (взаимное положение сохранено)."""
    steps = [WAIT, *_grid_on(10), *SELECT_CAP_BOLT, _snap("pre"), _drag(CAP_ONLY, 13, -17), _sleep(300), _snap("a")]
    _stand_, out = _go(start_pult, steps)
    assert _sel(out, "pre") == ["cap", "bolt"], f"precondition: Shift-клик добавил bolt к выбору: {_sel(out, 'pre')}"
    assert _offs(out, "a") == [[0, 0], [30, -20], [-50, -80]], (
        f"cap привязан к сетке, bolt сдвинут на ту же дельту, plate цел: {out['snaps']['a']['fields']}"
    )


def test_p2_grid_and_step_changes_are_silent(start_pult) -> None:
    """П.2: смена `#presetGrid`/`#presetGridStep` не меняет presetState, не шлёт запросов и не кладёт запись «Отмена»
    (после правки стрелкой первая «Отмена» откатывает ЕЁ). ЯКОРЬ: сетка при этом реально работает (привязка 25)."""
    steps = [
        WAIT, _click(CAP_ONLY), _key("ArrowRight"), *QUIET, _snap("s0"), _ui("u0"),
        _toggle("presetGrid", True), {"op": "type_field", "id": "presetGridStep", "value": 25},
        _toggle("presetGrid", False), _toggle("presetGrid", True), SETTLE, _snap("s1"), _ui("u1"),
        UNDO, _snap("s2"),
        _drag(CAP_ONLY, 13, -17), _sleep(300), _snap("anchor"),
    ]  # fmt: skip
    _stand_, out = _go(start_pult, steps)
    assert _offs(out, "s0")[1] == [21, 0], (
        f"precondition: стрелка → сдвинула cap на 1 px: {out['snaps']['s0']['fields']}"
    )
    assert out["snaps"]["s1"]["fields"] == out["snaps"]["s0"]["fields"], (
        "смена сетки/шага изменила поля формы (presetState)"
    )
    assert out["ui"]["u1"]["fetchCount"] == out["ui"]["u0"]["fetchCount"], (
        f"смена сетки/шага не шлёт запросов: {out['ui']['u0']['fetchCount']} -> {out['ui']['u1']['fetchCount']}"
    )
    assert _offs(out, "s2")[1] == [20, 0], (
        f"первая «Отмена» должна откатить стрелку (записи от сетки быть не должно): {out['snaps']['s2']['fields']}"
    )
    assert _offs(out, "anchor")[1] == [25, -25], (
        f"якорь: сетка 25 реально работает (сырое [33,-17] -> [25,-25]): {out['snaps']['anchor']['fields']}"
    )


def test_p2_arrows_are_not_snapped_to_grid(start_pult) -> None:
    """П.2: стрелки сеткой не привязываются: при сетке 25 → +1 по x, Shift+↓ +10 по y. ЯКОРЬ: сетка работает
    (потом жест (+13,-17) из [21,10] -> сырое [34,-7] -> привязанное [25,0])."""
    steps = [
        WAIT, *_grid_on(25), _click(CAP_ONLY), _key("ArrowRight"), _key("ArrowDown", shift=True), SETTLE, _snap("k"),
        _drag(CAP_ONLY, 13, -17), _sleep(300), _snap("anchor"),
    ]  # fmt: skip
    _stand_, out = _go(start_pult, steps)
    assert _offs(out, "k")[1] == [21, 10], (
        f"стрелки при вкл. сетке: свободные шаги 1 и 10 px: {out['snaps']['k']['fields']}"
    )
    assert _offs(out, "anchor")[1] == [25, 0], f"якорь привязки сетки 25: {out['snaps']['anchor']['fields']}"


# --------------------------------------------------------------------------- #
# П. 3 — мультивыбор                                                          #
# --------------------------------------------------------------------------- #
def test_p3_shift_click_toggles_membership_and_starts_no_gesture(start_pult) -> None:
    """П.3: Shift+ЛКМ на слое переключает членство (строки обоих выбранных несут `selected`), жеста не начинает:
    Shift-нажатие + движение + отпускание ничего не сдвигает."""
    steps = [
        WAIT, _click(CAP_ONLY), _snap("one"),
        _click(BOLT, shift=True), _snap("two"),
        {"op": "press_mod", "at": _at(BOLT), "shift": True},
        {"op": "move", "at": [_at(BOLT)[0] + 20, _at(BOLT)[1] + 20]},
        {"op": "move", "at": [_at(BOLT)[0] + 30, _at(BOLT)[1] + 30]},
        {"op": "release", "at": [_at(BOLT)[0] + 30, _at(BOLT)[1] + 30]},
        _sleep(250), _snap("three"),
    ]  # fmt: skip
    _stand_, out = _go(start_pult, steps)
    assert _sel(out, "one") == ["cap"], f"обычный клик: выбран один cap: {_sel(out, 'one')}"
    assert _sel(out, "two") == ["cap", "bolt"], f"Shift-клик на bolt добавил его к выбору: {_sel(out, 'two')}"
    assert _sel(out, "three") == ["cap"], (
        f"второй Shift на bolt исключил его из выбора (cap остался): {_sel(out, 'three')}"
    )
    assert _offs(out, "three") == _INITIAL, (
        f"Shift-нажатие не начинает жест, ничего не сдвигается: {_offs(out, 'three')}"
    )


def test_p3_drag_selected_moves_all_one_undo_one_layout_request(start_pult) -> None:
    """П.3: pointerdown без Shift на слое из выбора тащит ВСЕ выбранные: каждому та же дельта (+30,-10), ровно один
    POST /api/preset/layout, одна запись «Отмена» (одна «Отмена» возвращает все слои; вторая ничего не меняет)."""
    steps = [
        WAIT, *SELECT_CAP_BOLT, _snap("pre"),
        _drag(CAP_ONLY, 30, -10), _sleep(400), _snap("a"),
        UNDO, _snap("u1"), UNDO, _snap("u2"),
    ]  # fmt: skip
    _stand_, out = _go(start_pult, steps)
    assert _sel(out, "pre") == ["cap", "bolt"], f"precondition: выбраны cap и bolt: {_sel(out, 'pre')}"
    assert _offs(out, "a") == [[0, 0], [50, -10], [-30, -70]], (
        f"оба выбранных получили дельту (+30,-10), plate цел: {out['snaps']['a']['fields']}"
    )
    assert out["snaps"]["a"]["layoutCount"] == out["snaps"]["pre"]["layoutCount"] + 1, (
        f"ровно один новый POST /api/preset/layout за групповой жест: {out['snaps']['pre']['layoutCount']} -> "
        f"{out['snaps']['a']['layoutCount']}"
    )
    assert _offs(out, "u1") == _INITIAL, f"одна «Отмена» возвращает ВСЕ сдвинутые слои: {out['snaps']['u1']['fields']}"
    assert _offs(out, "u2") == _INITIAL, (
        f"вторая «Отмена» не должна ничего менять (запись одна): {out['snaps']['u2']['fields']}"
    )


def test_p3_press_on_unselected_layer_replaces_selection(start_pult) -> None:
    """П.3: pointerdown без Shift на слое ВНЕ выбора -> выбор = только он, и тащится только он."""
    steps = [WAIT, *SELECT_CAP_BOLT, _snap("pre"), _drag(PLATE_ONLY, 10, 0), _sleep(300), _snap("a")]
    _stand_, out = _go(start_pult, steps)
    assert _sel(out, "pre") == ["cap", "bolt"], f"precondition: выбраны cap и bolt: {_sel(out, 'pre')}"
    assert _sel(out, "a") == ["plate"], f"выбор = только plate: {_sel(out, 'a')}"
    assert _offs(out, "a") == [[10, 0], [20, 0], [-60, -60]], f"сдвинут только plate: {out['snaps']['a']['fields']}"


def test_p3_arrows_move_all_selected_one_undo_per_press(start_pult) -> None:
    """П.3: стрелки сдвигают все выбранные (1 px, Shift — 10), одна запись «Отмена» на нажатие."""
    steps = [
        WAIT, *SELECT_CAP_BOLT, _snap("pre"),
        _key("ArrowRight"), _snap("k1"), _key("ArrowDown", shift=True), _snap("k2"),
        UNDO, _snap("u1"), UNDO, _snap("u2"),
    ]  # fmt: skip
    _stand_, out = _go(start_pult, steps)
    assert _sel(out, "pre") == ["cap", "bolt"], f"precondition: выбраны cap и bolt: {_sel(out, 'pre')}"
    assert _offs(out, "k1") == [[0, 0], [21, 0], [-59, -60]], f"→: оба +1 по x: {out['snaps']['k1']['fields']}"
    assert _offs(out, "k2") == [[0, 0], [21, 10], [-59, -50]], f"Shift+↓: оба +10 по y: {out['snaps']['k2']['fields']}"
    assert _offs(out, "u1") == [[0, 0], [21, 0], [-59, -60]], (
        f"первая «Отмена» — только Shift+↓: {out['snaps']['u1']['fields']}"
    )
    assert _offs(out, "u2") == _INITIAL, f"вторая «Отмена» — стрелка →: {out['snaps']['u2']['fields']}"


@pytest.mark.parametrize("n_selected", [pytest.param(1, id="1"), pytest.param(2, id="2")])
def test_handles_only_for_single_selection(start_pult, n_selected: int) -> None:
    """П.3: ручка масштаба работает ТОЛЬКО при ровно одном выбранном слое. Жест от точки у правого нижнего угла рамки
    cap: при одном выбранном (контроль, как в 1.3h-b) scale растёт; при двух (cap+bolt) — scale не меняется."""
    select = [_click(CAP_ONLY)] if n_selected == 1 else SELECT_CAP_BOLT
    steps = [WAIT, *select, _snap("pre"), _drag(CAP_BR_CORNER, 20, 20), _sleep(300), _snap("a")]
    _stand_, out = _go(start_pult, steps)
    assert len(_sel(out, "pre")) == n_selected, f"precondition: выбрано {n_selected}, получено {_sel(out, 'pre')}"
    scales = [ly["scale"] for ly in out["snaps"]["a"]["layers"]]
    if n_selected == 1:
        assert scales[1] == pytest.approx(2.0, abs=0.05), (
            f"контроль: ручка масштаба при одном выбранном: scale={scales}"
        )
    else:
        assert scales == [1.0, 1.0, 1.0], f"при двух выбранных ручек нет, scale не меняется: {scales}"


# --------------------------------------------------------------------------- #
# П. 4 — горячие клавиши                                                      #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("key", ["Delete", "Backspace"])
def test_p4_delete_and_backspace_remove_all_selected_one_undo(start_pult, key: str) -> None:
    """П.4: Delete/Backspace удаляют ВСЕ выбранные слои одной записью «Отмена» (одна «Отмена» возвращает оба, в
    прежнем порядке и с прежними смещениями)."""
    steps = [
        WAIT,
        *SELECT_CAP_BOLT,
        _snap("pre"),
        _key(key),
        _sleep(200),
        _snap("a"),
        UNDO,
        _snap("u1"),
        UNDO,
        _snap("u2"),
    ]
    _stand_, out = _go(start_pult, steps)
    assert _sel(out, "pre") == ["cap", "bolt"], f"precondition: выбраны cap и bolt: {_sel(out, 'pre')}"
    assert _names(out, "a") == ["plate"], f"{key} удалил оба выбранных слоя: {_names(out, 'a')}"
    assert out["snaps"]["a"]["rows"] == ["plate"], f"строки формы после {key}: {out['snaps']['a']['rows']}"
    assert _names(out, "u1") == ["plate", "cap", "bolt"], (
        f"одна «Отмена» вернула оба слоя в порядке: {_names(out, 'u1')}"
    )
    assert _offs(out, "u1") == _INITIAL, f"со смещениями из пресета: {out['snaps']['u1']['fields']}"
    assert _names(out, "u2") == ["plate", "cap", "bolt"], (
        f"вторая «Отмена» ничего не меняет (запись одна): {_names(out, 'u2')}"
    )


@pytest.mark.parametrize("mod", ["ctrl", "meta"])
def test_p4_ctrl_z_and_meta_z_act_as_undo_button(start_pult, mod: str) -> None:
    """П.4: Ctrl+Z / Meta+Z = кнопка «Отмена»: откатывает правку стрелкой; повторное — на пустом стеке ничего."""
    steps = [
        WAIT, _click(CAP_ONLY), _key("ArrowRight"), _snap("edit"),
        {"op": "key_mod", "key": "z", mod: True}, _snap("z1"),
        {"op": "key_mod", "key": "z", mod: True}, _snap("z2"),
    ]  # fmt: skip
    _stand_, out = _go(start_pult, steps)
    assert _offs(out, "edit")[1] == [21, 0], f"precondition: стрелка сдвинула cap: {out['snaps']['edit']['fields']}"
    assert _offs(out, "z1")[1] == [20, 0], f"{mod}+Z откатил правку: {out['snaps']['z1']['fields']}"
    assert _offs(out, "z2") == _INITIAL, (
        f"повторный {mod}+Z на пустом стеке ничего не меняет: {out['snaps']['z2']['fields']}"
    )


def test_p4_ctrl_a_selects_all_and_prevents_default(start_pult) -> None:
    """П.4: Ctrl+A выбирает все видимые незапертые слои пресета (здесь все три; авто-слой base не выбирается) и
    вызывает preventDefault (иначе браузер выделит страницу)."""
    steps = [WAIT, _snap("pre"), {"op": "key_mod", "key": "a", "ctrl": True}, _snap("a")]
    _stand_, out = _go(start_pult, steps)
    assert _sel(out, "pre") == [], f"precondition: до Ctrl+A ничего не выбрано: {_sel(out, 'pre')}"
    assert _sel(out, "a") == ["plate", "cap", "bolt"], f"Ctrl+A выбрал все слои пресета: {_sel(out, 'a')}"
    assert out["pd"].count("a") >= 1, f"Ctrl+A должен вызвать preventDefault: {out['pd']}"


def test_p4_escape_clears_selection(start_pult) -> None:
    """П.4: Escape снимает выбор (ни одна строка не несёт `selected`)."""
    steps = [WAIT, *SELECT_CAP_BOLT, _snap("pre"), _key("Escape"), _snap("a")]
    _stand_, out = _go(start_pult, steps)
    assert _sel(out, "pre") == ["cap", "bolt"], f"precondition: выбраны cap и bolt: {_sel(out, 'pre')}"
    assert _sel(out, "a") == [], f"Escape снял выбор: {_sel(out, 'a')}"


def test_p4_g_and_shift_g_toggle_grid(start_pult) -> None:
    """П.4: `g` и `G` переключают #presetGrid (вкл -> выкл -> вкл)."""
    steps = [
        WAIT, _ui("u0", ["presetGrid"]), _key("g"), _ui("u1", ["presetGrid"]),
        _key("G", shift=True), _ui("u2", ["presetGrid"]), _key("g"), _ui("u3", ["presetGrid"]),
    ]  # fmt: skip
    _stand_, out = _go(start_pult, steps)
    got = [out["ui"][t]["checked"]["presetGrid"] for t in ("u0", "u1", "u2", "u3")]
    assert got == [False, True, False, True], f"presetGrid после [-, g, G, g] должен быть [выкл, вкл, выкл, вкл]: {got}"


def test_p4_hotkeys_ignored_when_focus_in_form_field(start_pult) -> None:
    """П.4: пока источник события — INPUT/TEXTAREA/SELECT, горячие клавиши (Delete, Backspace, g, f, Ctrl+A, Escape)
    игнорируются: слои целы, сетка и масштаб прежние, выбор цел. ЯКОРЬ: тот же Delete с канвы удаляет cap."""
    steps = [WAIT, _click(CAP_ONLY), _snap("pre")]
    for tgt, key in (
        ("INPUT", "Delete"),
        ("INPUT", "Backspace"),
        ("SELECT", "g"),
        ("TEXTAREA", "f"),
        ("INPUT", "Escape"),
    ):
        steps.append(_key(key, target=tgt))
    steps += [
        {"op": "key_mod", "key": "a", "ctrl": True, "target": "INPUT"}, _sleep(100),
        _snap("held"), _ui("uheld", ["presetGrid"]),
        _key("Delete"), _sleep(200), _snap("anchor"),
    ]  # fmt: skip
    _stand_, out = _go(start_pult, steps)
    held = out["snaps"]["held"]
    assert held["rows"] == ["plate", "cap", "bolt"], f"из поля слои удалять нельзя: {held['rows']}"
    assert held["selected"] == ["cap"], f"из поля выбор не менялся (Escape/Ctrl+A): {held['selected']}"
    assert held["fields"]["presetZoom"] == "100", f"из поля `f` масштаб не меняет: {held['fields']['presetZoom']}"
    assert out["ui"]["uheld"]["checked"]["presetGrid"] is False, "из поля `g` сетку не переключает"
    assert out["snaps"]["anchor"]["rows"] == ["plate", "bolt"], (
        f"якорь: Delete с канвы удаляет выбранный cap (клавиши работают): {out['snaps']['anchor']['rows']}"
    )


@pytest.mark.parametrize(
    "control, checked",
    [
        pytest.param("presetGrid", True, id="grid"),
        pytest.param("presetVis2", False, id="vis"),
        pytest.param("presetLock2", True, id="lock"),
    ],
)
def test_p4_checkbox_click_returns_focus_to_canvas(start_pult, control: str, checked: bool) -> None:
    """П.4: после клика по чекбоксу п.1 фокус возвращается на канву (активный элемент — `presetCanvas`); следующая
    стрелка (источник = document.activeElement) двигает выбранный cap, а не теряется в «поле»."""
    steps = [
        WAIT, _click(CAP_ONLY), _toggle(control, checked), _snap("after"),
        _key("ArrowRight", target="ACTIVE"), _snap("moved"),
    ]  # fmt: skip
    _stand_, out = _go(start_pult, steps)
    assert out["snaps"]["after"]["active"] == "presetCanvas", (
        f"после клика по {control} фокус должен быть на канве, а не на чекбоксе: {out['snaps']['after']['active']!r}"
    )
    assert _offs(out, "moved")[1] == [21, 0], (
        f"стрелка после клика по {control} должна дойти до слоя: {out['snaps']['moved']['fields']}"
    )


# --------------------------------------------------------------------------- #
# П. 5 — вписать                                                              #
# --------------------------------------------------------------------------- #
def _fit_z(cw: int, ch: int, w: int = 640, h: int = 480) -> int:
    """Z из ФОРМУЛЫ контракта; W,H — размер холста харнесса (640x480), cw/ch — canvas_px раскладки."""
    return max(10, min(1000, math.floor(95 * min(w / cw, h / ch))))


@pytest.mark.parametrize(
    "canvas, literal",
    [
        pytest.param((300, 200), 202, id="normal"),  # 95*min(2.1333, 2.4) = 202.67 -> 202
        pytest.param((10, 10), 1000, id="clamp_max"),  # 95*min(64, 48) = 4560 -> 1000
        pytest.param((8000, 8000), 10, id="clamp_min"),  # 95*min(0.08, 0.06) = 5.7 -> 5 -> 10
    ],
)
def test_p5_fit_button_sets_zoom_by_formula(start_pult, canvas: tuple[int, int], literal: int) -> None:
    """П.5: btnPresetFit -> presetZoom.value == String(Z), Z = clamp(floor(95*min(W/cw,H/ch)), 10, 1000)."""
    assert _fit_z(*canvas) == literal, "самопроверка: формула теста совпала с литералом"
    steps = [WAIT, _snap("pre"), {"op": "press_button", "id": "btnPresetFit"}, _sleep(150), _snap("a")]
    _stand_, out = _go(start_pult, steps, canvas)
    assert out["snaps"]["pre"]["fields"]["presetZoom"] == "100", "precondition: масштаб до «Вписать» — 100"
    assert out["snaps"]["a"]["fields"]["presetZoom"] == str(literal), (
        f"canvas_px {canvas} на холсте 640x480: Z должен быть {literal}: {out['snaps']['a']['fields']['presetZoom']!r}"
    )


@pytest.mark.parametrize("key", ["f", "F"])
def test_p5_fit_hotkey(start_pult, key: str) -> None:
    """П.5: клавиши f/F делают то же, что btnPresetFit."""
    steps = [WAIT, _key(key, shift=(key == "F")), _sleep(150), _snap("a")]
    _stand_, out = _go(start_pult, steps, (300, 200))
    assert out["snaps"]["a"]["fields"]["presetZoom"] == "202", (
        f"`{key}` -> Z=202: {out['snaps']['a']['fields']['presetZoom']!r}"
    )


def test_p5_fit_resets_pan_object_center_at_canvas_center(start_pult) -> None:
    """П.5: «Вписать» сбрасывает панораму — центр объекта в центре канвы. Сдвинули панораму средней кнопкой на 150 px,
    «Вписать» (canvas 200x200 -> Z=228): пиксель на 80 px правее центра холста — объект (135,100) = cap (красный)."""
    z = _fit_z(200, 200)
    assert z == 228, f"самопроверка формулы: {z}"
    steps = [
        WAIT, {"op": "drag", "from": [0, 0], "to": [150, 0], "button": 1, "steps": 4}, _sleep(100),
        {"op": "press_button", "id": "btnPresetFit"}, _sleep(200),
        {"op": "pixel", "tag": "p", "at": [80, 0]}, _snap("a"),
    ]  # fmt: skip
    _stand_, out = _go(start_pult, steps)
    assert out["snaps"]["a"]["fields"]["presetZoom"] == "228", f"Z=228: {out['snaps']['a']['fields']['presetZoom']!r}"
    assert out["pixels"]["p"] == RED, (
        f"при Z=228 и сброшенной панораме пиксель (+80,0) = объект (135.09,100.2) = cap: {out['pixels']['p']}"
    )


def test_p5_fit_sends_no_requests_and_leaves_undo_alone(start_pult) -> None:
    """П.5: «Вписать» не шлёт запросов и не трогает «Отмену»: после правки стрелкой и `f` первая «Отмена»
    откатывает стрелку. ЯКОРЬ: `f` реально сработал (Z=202)."""
    steps = [
        WAIT, _click(CAP_ONLY), _key("ArrowRight"), *QUIET, _ui("u0"),
        _key("f"), _sleep(200), _ui("u1"), _snap("fit"),
        UNDO, _snap("u"),
    ]  # fmt: skip
    _stand_, out = _go(start_pult, steps, (300, 200))
    assert out["snaps"]["fit"]["fields"]["presetZoom"] == "202", "якорь: `f` вписал (Z=202)"
    assert out["ui"]["u1"]["fetchCount"] == out["ui"]["u0"]["fetchCount"], (
        f"«Вписать» не шлёт запросов: {out['ui']['u0']['fetchCount']} -> {out['ui']['u1']['fetchCount']}"
    )
    assert _offs(out, "u")[1] == [20, 0], (
        f"первая «Отмена» откатывает стрелку, а не «Вписать»: {out['snaps']['u']['fields']}"
    )


# --------------------------------------------------------------------------- #
# П. 6 — видимость и замок                                                    #
# --------------------------------------------------------------------------- #
def test_p6_hidden_layer_not_drawn_pixels_come_from_below(start_pult) -> None:
    """П.6: снятый presetVis1 (cap): на его месте пиксели слоя ниже (plate в перекрытии, base вне plate);
    возврат флага возвращает cap. Контроль до переключения: пиксели красные."""
    steps = [
        WAIT, _px("c0", CAP_ONLY), _px("o0", OVERLAP),
        _toggle("presetVis1", False), SETTLE, _sleep(150), _px("c1", CAP_ONLY), _px("o1", OVERLAP),
        _toggle("presetVis1", True), SETTLE, _sleep(150), _px("c2", CAP_ONLY),
    ]  # fmt: skip
    _stand_, out = _go(start_pult, steps)
    px = out["pixels"]
    assert (px["c0"], px["o0"]) == (RED, RED), (
        f"контроль: cap виден и в одиночной, и в перекрытой точке: {px['c0']} {px['o0']}"
    )
    assert px["c1"] == GRAY, f"cap скрыт: на (135,100) остался base (серый), а не красный: {px['c1']}"
    assert px["o1"] == BLUE, f"cap скрыт: на (110,100) виден plate под ним: {px['o1']}"
    assert px["c2"] == RED, f"флаг возвращён: cap снова нарисован: {px['c2']}"


def test_p6_hidden_layer_click_passes_below_and_leaves_selection(start_pult) -> None:
    """П.6: скрытый слой выбрать нельзя (клик проходит к слою ниже: в перекрытии выбирается plate) и он убирается из
    выбора при скрытии."""
    steps = [
        WAIT, _click(CAP_ONLY), _snap("s0"), _toggle("presetVis1", False), _snap("s1"),
        _click(OVERLAP), _snap("s2"), _click(CAP_ONLY), _snap("s3"),
    ]  # fmt: skip
    _stand_, out = _go(start_pult, steps)
    assert _sel(out, "s0") == ["cap"], f"precondition: cap выбран кликом: {_sel(out, 's0')}"
    assert _sel(out, "s1") == [], f"скрытие убрало cap из выбора: {_sel(out, 's1')}"
    assert _sel(out, "s2") == ["plate"], f"клик в перекрытие при скрытом cap выбрал plate под ним: {_sel(out, 's2')}"
    assert "cap" not in _sel(out, "s3"), f"клик по месту скрытого cap его не выбирает: {_sel(out, 's3')}"


def test_p6_locked_layer_drawn_but_click_and_drag_pass_below(start_pult) -> None:
    """П.6: запертый cap рисуется (красный), но не выбирается и не тащится: клик в перекрытие выбирает plate, жест
    от перекрытия двигает plate, а cap остаётся на месте."""
    steps = [
        WAIT, _toggle("presetLock1", True), SETTLE, _sleep(100), _px("c", CAP_ONLY),
        _click(CAP_ONLY), _snap("s_cap"), _click(OVERLAP), _snap("s_ov"),
        _drag(OVERLAP, 25, 0), _sleep(300), _snap("a"),
    ]  # fmt: skip
    _stand_, out = _go(start_pult, steps)
    assert out["pixels"]["c"] == RED, f"запертый слой рисуется: {out['pixels']['c']}"
    assert "cap" not in _sel(out, "s_cap"), f"запертый cap не выбирается кликом: {_sel(out, 's_cap')}"
    assert _sel(out, "s_ov") == ["plate"], f"клик в перекрытие прошёл к plate: {_sel(out, 's_ov')}"
    assert _offs(out, "a") == [[25, 0], [20, 0], [-60, -60]], (
        f"жест тащит plate; запертый cap не сдвинут: {out['snaps']['a']['fields']}"
    )


def test_p6_lock_leaves_selection_and_arrows_delete_skip_locked(start_pult) -> None:
    """П.6: запирание убирает слой из выбора (cap+bolt, запираем bolt -> выбран только cap); стрелки и Delete
    запертый bolt не трогают."""
    steps = [
        WAIT, *SELECT_CAP_BOLT, _snap("pre"), _toggle("presetLock2", True), _snap("s1"),
        _key("ArrowRight"), _snap("k"), _key("Delete"), _sleep(200), _snap("d"),
    ]  # fmt: skip
    _stand_, out = _go(start_pult, steps)
    assert _sel(out, "pre") == ["cap", "bolt"], f"precondition: выбраны cap и bolt: {_sel(out, 'pre')}"
    assert _sel(out, "s1") == ["cap"], f"запирание убрало bolt из выбора: {_sel(out, 's1')}"
    assert _offs(out, "k") == [[0, 0], [21, 0], [-60, -60]], (
        f"стрелка сдвинула только cap: {out['snaps']['k']['fields']}"
    )
    assert out["snaps"]["d"]["rows"] == ["plate", "bolt"], (
        f"Delete удалил только cap, запертый bolt остался: {out['snaps']['d']['rows']}"
    )


def test_p6_ctrl_a_takes_only_visible_unlocked(start_pult) -> None:
    """П.6: Ctrl+A при скрытом cap и запертом bolt выбирает только plate; после отпирания bolt — plate и bolt."""
    steps = [
        WAIT, _toggle("presetVis1", False), _toggle("presetLock2", True),
        {"op": "key_mod", "key": "a", "ctrl": True}, _snap("a"),
        _toggle("presetLock2", False), {"op": "key_mod", "key": "a", "ctrl": True}, _snap("b"),
    ]  # fmt: skip
    _stand_, out = _go(start_pult, steps)
    assert _sel(out, "a") == ["plate"], f"Ctrl+A: скрытый cap и запертый bolt не берутся: {_sel(out, 'a')}"
    assert _sel(out, "b") == ["plate", "bolt"], (
        f"после отпирания bolt Ctrl+A берёт его (cap всё ещё скрыт): {_sel(out, 'b')}"
    )


def _scenario_edit_then_save(extra: list[dict]) -> list[dict]:
    return [WAIT, _click(CAP_ONLY), *extra, _key("ArrowRight"), *QUIET, SAVE, SETTLE, _px("bolt", BOLT)]


def test_p6_flags_do_not_reach_commit_or_layout_bodies(start_pult) -> None:
    """П.6: тела POST /api/preset/commit и /api/preset/layout с переключёнными флагами побайтно равны телам без них;
    presetState не получает флагов; набор маршрутов тот же. ЯКОРЬ: во втором прогоне флаги реально действуют
    (bolt скрыт — на его месте серый base)."""
    _s1, plain = _go(start_pult, _scenario_edit_then_save([]))
    flags = [_toggle("presetVis2", False), _toggle("presetLock0", True)]
    _s2, flagged = _go(start_pult, _scenario_edit_then_save(flags) + [_snap("end")])
    assert flagged["pixels"]["bolt"] == GRAY, (
        f"якорь: скрытый bolt не нарисован (флаг действует): {flagged['pixels']['bolt']}"
    )
    assert plain["pixels"]["bolt"] == GREEN, "контроль: без флага bolt нарисован"

    def bodies(out: dict, path: str) -> list[str]:
        return [e["body"] for e in out["fetchLog"] if e["path"] == path and e["method"] == "POST"]

    assert bodies(flagged, "/api/preset/commit") == bodies(plain, "/api/preset/commit") != [], (
        f"тело commit с флагами должно быть побайтно равно телу без них: {bodies(flagged, '/api/preset/commit')!r} "
        f"vs {bodies(plain, '/api/preset/commit')!r}"
    )
    assert set(bodies(flagged, "/api/preset/layout")) == set(bodies(plain, "/api/preset/layout")), (
        "набор тел /api/preset/layout с флагами должен совпасть с набором без них"
    )
    assert {(e["method"], e["path"]) for e in flagged["fetchLog"]} == {
        (e["method"], e["path"]) for e in plain["fetchLog"]
    }, "флаги не должны порождать новых маршрутов/методов"
    assert flagged["snaps"]["end"]["layers"] == [
        {**_layer("plate", 0, 0)},
        {**_layer("cap", 21, 0)},
        {**_layer("bolt", -60, -60)},
    ], f"в presetState.layers нет полей флагов: {flagged['snaps']['end']['layers']}"


def test_p6_flags_do_not_push_undo_records(start_pult) -> None:
    """П.6: переключение флагов не кладёт записей «Отмена»: правка стрелкой, затем флаги, затем ОДНА «Отмена» —
    откатывает стрелку (запись флага стояла бы выше). ЯКОРЬ: флаг действует (скрытый bolt не нарисован); «Отмена»
    состояние флагов не откатывает."""
    steps = [
        WAIT, _click(CAP_ONLY), _key("ArrowRight"), *QUIET,
        _toggle("presetVis2", False), _toggle("presetLock0", True), SETTLE, _sleep(150), _px("hid", BOLT),
        UNDO, _snap("u"), SETTLE, _sleep(150), _px("hid2", BOLT),
    ]  # fmt: skip
    _stand_, out = _go(start_pult, steps)
    assert out["pixels"]["hid"] == GRAY, f"якорь: скрытый bolt не нарисован: {out['pixels']['hid']}"
    assert _offs(out, "u")[1] == [20, 0], (
        f"одна «Отмена» после флагов откатывает стрелку: {out['snaps']['u']['fields']}"
    )
    assert out["pixels"]["hid2"] == GRAY, (
        f"«Отмена» не меняет клиентские флаги: bolt остаётся скрытым: {out['pixels']['hid2']}"
    )


def test_p6_flags_follow_layer_name_through_delete_and_field_edit(start_pult) -> None:
    """П.6: флаги привязаны к ИМЕНИ слоя и переживают перестройку строк и новую раскладку: скрыли cap (инд.1), заперли
    bolt (инд.2), удалили plate (инд.0) -> cap стал инд.0, bolt инд.1: presetVis0 снят, presetVis1 отмечен,
    presetLock0 снят, presetLock1 отмечен; cap по-прежнему не рисуется, bolt не выбирается; после правки поля
    (cap offset_x=25) cap всё ещё скрыт."""
    ids = ["presetVis0", "presetVis1", "presetLock0", "presetLock1"]
    steps = [
        WAIT, _toggle("presetVis1", False), _toggle("presetLock2", True), SETTLE,
        _click(PLATE_ONLY), _snap("sel"), {"op": "press_button", "id": "btnLayerDelete"}, SETTLE, _sleep(150),
        _snap("del"), _ui("flags", ids), _px("cap1", CAP_ONLY), _click(BOLT), _snap("bolt_click"),
        {"op": "set_field", "id": _F(0, "x"), "value": 25},
        {"op": "fire_el", "id": "presetLayers", "type": "change"},
        SETTLE, _sleep(150), _px("cap2", CAP_ONLY), _ui("flags2", ids),
    ]  # fmt: skip
    _stand_, out = _go(start_pult, steps)
    assert _sel(out, "sel") == ["plate"] and _names(out, "del") == ["cap", "bolt"], (
        f"precondition: plate выбран и удалён, остались cap и bolt: {_sel(out, 'sel')} {_names(out, 'del')}"
    )
    for tag in ("flags", "flags2"):
        c = out["ui"][tag]["checked"]
        assert c == {"presetVis0": False, "presetVis1": True, "presetLock0": False, "presetLock1": True}, (
            f"после перестройки флаги должны остаться у своих слоёв (cap: скрыт; bolt: заперт) — {tag}: {c}"
        )
    assert out["pixels"]["cap1"] == GRAY, f"скрытый cap после удаления plate не нарисован: {out['pixels']['cap1']}"
    assert "bolt" not in _sel(out, "bolt_click"), (
        f"запертый bolt после перестройки не выбирается: {_sel(out, 'bolt_click')}"
    )
    assert out["pixels"]["cap2"] == GRAY, (
        f"после правки поля и новой раскладки cap всё ещё скрыт: {out['pixels']['cap2']}"
    )
