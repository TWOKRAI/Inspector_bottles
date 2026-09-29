# -*- coding: utf-8 -*-
"""RED-приёмка Task 1.3h-c-fix — фокус после кнопок редактора слоёв (F1) и выбор после «Отмены» (F2).

Независимый tester вслепую, worktree `ls-13hc-fix-tester`, коммит `98bec3a4` (исправления в дереве нет).
Источник — только раздел «Task 1.3h-c-fix» и раздел «Приёмка лида» плана
`plans/line-sim-layer-editor/task-1.3h-c-layers.md`. Реализация страницы (`plugin.py`) НЕ читалась.

Контракт, который пинит этот файл (своими словами)
====================================================
F1. Браузер отдаёт нажатой кнопке фокус. Пока он остаётся на кнопке, Space/Enter нажмут её ещё раз (и Space,
который в редакторе — «панорама», повторит кнопку: три «Добавить» вместо одного, повторная запись «Сохранить»).
Поэтому ЛЮБАЯ кнопка редактора слоёв (`btnPresetPreview`, `btnPresetSave`, `btnPresetUndo`, `btnLayerAdd`,
`btnLayerSprite`, `btnLayerDelete`, `btnLayerUp`, `btnLayerDown`, `btnSpritesRefresh`) после нажатия обязана
перевести фокус на канву `#presetCanvas` вызовом `focus({ preventScroll: true })` (страница не прыгает) —
и когда кнопка что-то сделала, и когда она была no-op (пустой стек «Отмены», ничего не выбрано).
Следом Space, источник которого `document.activeElement`, включает панораму (как Space над канвой): слой под
указателем при перетаскивании НЕ сдвигается. Кнопки ВНЕ редактора (пульт ленты, сцена) фокус не трогают.

F2. «Добавить» -> «Отмена»: слой исчез, выбора нет (`presetSelected === null`), подсветки строки нет, стрелки не
создают записей «Отмена» и запросов раскладки. «Отмена», после которой выбранный слой остался (сдвиг выбранного
стрелкой -> «Отмена»), выбор СОХРАНЯЕТ.

Как это измеряется (что харнесс `page_offline.mjs` видит, а что нет)
---------------------------------------------------------------------
- Харнесс НЕ моделирует, что клик по кнопке отдаёт ей фокус: `press_button` шлёт только `click`. Поэтому перед
  каждым нажатием кнопки шаг `focus_el` ставит фокус на неё сам (как это делает браузер при клике), а снимок
  «focused» доказывает, что предусловие выполнено. Что браузер по Space/Enter нажимает сфокусированную кнопку,
  харнесс НЕ видит — этот файл этого НЕ проверяет и НЕ утверждает; он проверяет только то, что виден:
  `document.activeElement`, опции вызовов `focus()` канвы, поведение панорамы, слои, запросы раскладки.
- `presetSelected` снимок не показывает (шаг `snap` отдаёт лишь подсвеченные строки). Прямая проверка «выбор
  сброшен» поэтому НЕ выразима; косвенная — «устаревшее имя выбора не оживает»: после «Добавить a» -> «Отмена»
  слой `cap` переименовывается в `a` (форма 1.2h, поле `layer2_name`); если `presetSelected` остался на «a», строка
  с этим именем становится выбранной и стрелка сдвигает чужой слой (наблюдение до исправления: offset -70 -> -69,
  один лишний запрос раскладки, подсвеченная строка `a`).
- Панорама наблюдается через слой: при зажатом Space перетаскивание слоя не двигает его; после `keyup` обычное
  перетаскивание двигает (положительный контроль в том же тесте — иначе «слой не сдвинулся» вакуумно).
"""

# ruff: noqa: F811  (start_pult — фикстура из соседнего файла: ре-импорт и параметр теста)

from __future__ import annotations

import urllib.request

import pytest

from Plugins.sim.pult_web.tests.test_acceptance_1_3h_c_layers import (  # noqa: F401  (start_pult — фикстура)
    _A,
    _B,
    _C,
    _INITIAL,
    _READY,
    _SETTLE,
    _UNDO,
    _AT_DISK,
    _Ids,
    _assert_ran,
    _btn,
    _click,
    _eff,
    _pick,
    _run_canvas,
    _snap,
    _stand,
    start_pult,
)

pytestmark = pytest.mark.timeout(60)

_PS = {"preventScroll": True}

_EDITOR_BUTTONS = [
    "btnPresetPreview",
    "btnPresetSave",
    "btnPresetUndo",
    "btnLayerAdd",
    "btnLayerSprite",
    "btnLayerDelete",
    "btnLayerUp",
    "btnLayerDown",
    "btnSpritesRefresh",
]
#: Кнопки вне редактора слоёв (id взяты из сценариев харнесса: сцена — «Выпусти брак» / частота, правда — «Сброс»).
_OUTSIDE_BUTTONS = ["btnSceneDefectNow", "btnSceneDefectRate", "btnTruthReset"]

_SPACE = {"op": "key", "key": " ", "code": "Space"}  # источник — канва (по умолчанию), как «Space над канвой»
_SPACE_ACTIVE = {**_SPACE, "target": "ACTIVE"}  # источник — document.activeElement (куда браузер шлёт пробел)
_KEYUP_SPACE = {"op": "keyup", "key": " "}
_AT_DISK_ONLY = [
    40,
    30,
]  # объект (140, 130): непрозрачен только у disk (letter 85..115 по y, новый слой 40x40 в центре)
_DRAG_30 = {"op": "drag", "from": _AT_DISK_ONLY, "to": [70, 30]}


def _focus(button_id: str) -> dict:
    """Как клик мышью по кнопке в браузере: кнопка получает фокус (харнесс сам этого не делает)."""
    return {"op": "focus_el", "id": button_id}


def _new_focus_calls(before: dict, after: dict) -> list:
    """Вызовы `presetCanvas.focus()`, появившиеся между двумя снимками."""
    return after["focusCalls"][len(before["focusCalls"]) :]


# --------------------------------------------------------------------------- #
# Страховка от вакуума: все id, которыми оперируют тесты, есть в разметке GET / #
# --------------------------------------------------------------------------- #
def test_markup_has_every_button_the_tests_press(start_pult) -> None:
    """Харнесс создаёт узел под любой id — без разбора HTML тест на «кнопка перевела фокус» мог бы нажимать
    несуществующую кнопку. Все девять кнопок редактора и три контрольные кнопки вне его есть в разметке по разу."""
    port = start_pult()
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as resp:
        html = resp.read().decode("utf-8")
    parser = _Ids()
    parser.feed(html)
    wanted = [*_EDITOR_BUTTONS, *_OUTSIDE_BUTTONS, "presetCanvas"]
    missing = [i for i in wanted if i not in parser.tags]
    assert not missing, f"в разметке `GET /` нет id: {missing}"
    assert all(parser.tags[b] == ["button"] for b in [*_EDITOR_BUTTONS, *_OUTSIDE_BUTTONS]), (
        f"каждая кнопка — ровно один <button>: { {b: parser.tags[b] for b in wanted} }"
    )


# --------------------------------------------------------------------------- #
# F1 — фокус уходит на канву после КАЖДОЙ кнопки редактора                    #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("button_id", _EDITOR_BUTTONS)
def test_f1_editor_button_moves_focus_to_canvas_with_prevent_scroll(start_pult, button_id: str) -> None:
    """F1: слой выбран, в «Отмене» есть запись, в списке выбран a.png — кнопка РАБОТАЕТ; после неё
    `document.activeElement` — `presetCanvas`, а новые вызовы `focus()` канвы все с `{ preventScroll: true }`."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            _SETTLE,
            _click(_AT_DISK),  # выбрать disk (сам клик по канве фокус на канву уже переводит — B1)
            {"op": "key", "key": "ArrowRight"},  # одна запись «Отмена»: кнопке «Отмена» есть что отменять
            _pick(_A),
            _focus(button_id),
            _snap("focused"),
            _btn(button_id),
            _SETTLE,
            _snap("after"),
        ],
    )
    _assert_ran(out)
    focused, after = out["snaps"]["focused"], out["snaps"]["after"]
    assert focused["active"] == button_id, (
        f"предусловие: фокус на кнопке {button_id} (шаг focus_el): {focused['active']!r}"
    )
    assert after["active"] == "presetCanvas", (
        f"после нажатия {button_id} фокус должен уйти на канву, а он на {after['active']!r}"
    )
    new_calls = _new_focus_calls(focused, after)
    assert new_calls, f"{button_id}: страница не вызвала presetCanvas.focus(): {after['focusCalls']!r}"
    assert all(c == _PS for c in new_calls), (
        f"{button_id}: focus() канвы вызван не с {{ preventScroll: true }} (страница прыгнет): {new_calls!r}"
    )


@pytest.mark.parametrize(
    "button_id", ["btnPresetUndo", "btnLayerSprite", "btnLayerDelete", "btnLayerUp", "btnLayerDown"]
)
def test_f1_noop_button_also_moves_focus(start_pult, button_id: str) -> None:
    """F1 (no-op): пустой стек «Отмены» / ничего не выбрано — кнопка ничего не меняет (слои те же, выбора нет,
    раскладка не запрошена — положительный контроль «это правда no-op»), и всё равно фокус уходит на канву
    с `{ preventScroll: true }`. Иначе Space после такого клика нажал бы кнопку, как только слой выберут."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            _SETTLE,
            _pick(_A),
            _focus(button_id),
            _snap("focused"),
            _btn(button_id),
            _SETTLE,
            _snap("after"),
        ],
    )
    _assert_ran(out)
    focused, after = out["snaps"]["focused"], out["snaps"]["after"]
    assert focused["active"] == button_id, f"предусловие: фокус на кнопке: {focused['active']!r}"
    # это правда no-op: состав слоёв (и форма) прежние, выбора нет
    assert _eff(after) == _INITIAL, f"{button_id} без выбора/стека должна быть no-op, а слои стали {_eff(after)!r}"
    assert after["selected"] == [], f"ничего не выбрано: {after['selected']!r}"
    if button_id != "btnPresetUndo":  # что «Отмена» с пустым стеком шлёт раскладке — контрактом не задано
        assert after["layoutCount"] == focused["layoutCount"], f"no-op не запрашивает раскладку: {after['layoutCount']}"
    # ... но фокус переведён
    assert after["active"] == "presetCanvas", f"no-op {button_id}: фокус остался на {after['active']!r}"
    new_calls = _new_focus_calls(focused, after)
    assert new_calls and all(c == _PS for c in new_calls), (
        f"no-op {button_id}: focus() канвы с {{ preventScroll: true }} не вызван: {new_calls!r}"
    )


@pytest.mark.parametrize("button_id", ["btnSpritesRefresh", "btnPresetUndo", "btnLayerAdd", "btnPresetSave"])
def test_f1_space_after_button_starts_pan_instead_of_moving_layer(start_pult, button_id: str) -> None:
    """F1: после кнопки Space, источник которого `document.activeElement`, включает панораму — перетаскивание
    слоя disk при зажатом Space НЕ сдвигает его (offset остаётся [0, 0]); после `keyup` то же перетаскивание
    ДВИГАЕТ слой на +30 (положительный контроль: перетаскивание в этой странице вообще работает)."""
    stand = _stand(start_pult, _INITIAL)
    expected_layers = 4 if button_id == "btnLayerAdd" else 3
    out = _run_canvas(
        stand.port,
        [
            _READY,
            _SETTLE,
            _pick(_A),
            _focus(button_id),
            _btn(button_id),
            _SETTLE,
            _snap("before_space"),
            _SPACE_ACTIVE,
            _DRAG_30,
            _SETTLE,
            _snap("panned"),
            _KEYUP_SPACE,
            _DRAG_30,
            _SETTLE,
            _snap("dragged"),
        ],
    )
    _assert_ran(out)
    before, panned, dragged = (out["snaps"][k] for k in ("before_space", "panned", "dragged"))
    assert len(_eff(panned)) == expected_layers, f"после {button_id} слоёв {len(_eff(panned))}, ждали {expected_layers}"
    assert _eff(panned)[0]["offset_px"] == [0, 0], (
        f"после {button_id} Space(источник = activeElement={before['active']!r}) не включил панораму — "
        f"перетаскивание сдвинуло слой disk: offset_px={_eff(panned)[0]['offset_px']!r}"
    )
    assert _eff(dragged)[0]["offset_px"] == [30, 0], (
        f"контроль: без Space перетаскивание двигает disk на +30: {_eff(dragged)[0]['offset_px']!r}"
    )


def test_control_space_over_canvas_pans_and_plain_drag_moves(start_pult) -> None:
    """Контроль (зелёный и до исправления): Space над канвой = панорама (слой не двигается), после `keyup` drag
    двигает слой. Задаёт эталон, с которым сравнивается F1: «Space с источником activeElement — как над канвой»."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            _SETTLE,
            _SPACE,
            _DRAG_30,
            _SETTLE,
            _snap("panned"),
            _KEYUP_SPACE,
            _DRAG_30,
            _SETTLE,
            _snap("dragged"),
        ],
    )
    _assert_ran(out)
    assert _eff(out["snaps"]["panned"])[0]["offset_px"] == [0, 0], "Space над канвой: слой не сдвинут (панорама)"
    assert _eff(out["snaps"]["dragged"])[0]["offset_px"] == [30, 0], "без Space перетаскивание двигает слой на +30"


@pytest.mark.parametrize("button_id", _OUTSIDE_BUTTONS)
def test_f1_control_buttons_outside_editor_keep_focus(start_pult, button_id: str) -> None:
    """F1 контроль (зелёный и до исправления): кнопки вне редактора слоёв фокус не трогают — `activeElement`
    остаётся на кнопке, канва `focus()` не вызывала (число вызовов то же)."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [_READY, _SETTLE, _focus(button_id), _snap("focused"), _btn(button_id), _SETTLE, _snap("after")],
    )
    _assert_ran(out)
    focused, after = out["snaps"]["focused"], out["snaps"]["after"]
    assert focused["active"] == button_id, f"предусловие: фокус на кнопке: {focused['active']!r}"
    assert after["active"] == button_id, (
        f"кнопка вне редактора {button_id} не должна уводить фокус: {after['active']!r}"
    )
    assert _new_focus_calls(focused, after) == [], (
        f"{button_id}: канва не должна получать focus(): {after['focusCalls']!r}"
    )


# --------------------------------------------------------------------------- #
# F2 — выбор после «Отмены»                                                   #
# --------------------------------------------------------------------------- #
def test_f2_add_then_undo_leaves_no_highlighted_row(start_pult) -> None:
    """F2: «Добавить a» -> слой выбран и подсвечен (положительный контроль); «Отмена» -> слоя нет, подсвеченных
    строк нет. (Видимое следствие — до исправления уже зелёное: подсветка ищет строку по имени и не находит.)"""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [_READY, _SETTLE, _pick(_A), _btn("btnLayerAdd"), _SETTLE, _snap("added"), _UNDO, _SETTLE, _snap("undone")],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert s["added"]["selected"] == ["a"], f"контроль: «Добавить» выбирает новый слой: {s['added']['selected']!r}"
    assert _eff(s["undone"]) == _INITIAL, f"«Отмена» убрала слой: {_eff(s['undone'])!r}"
    assert s["undone"]["selected"] == [], f"после «Добавить» -> «Отмена» выбора нет: {s['undone']['selected']!r}"


def test_f2_add_then_undo_arrows_are_inert_and_write_no_undo_record(start_pult) -> None:
    """F2: после «Добавить» -> «Отмена» стрелка не шлёт раскладку и не пишет запись «Отмена». Запись ловится цепочкой:
    три «Добавить» (записи R1..R3), «Отмена» (снимает R3; выбранный `b` исчез), стрелка, «Отмена» — если стрелка
    записала лишнее, эта «Отмена» снимет её и слоёв останется 5, а не 4. (До исправления зелёное: стрелки
    молча инертны — тест держит эту инертность и после.)"""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            _SETTLE,
            _pick(_A),
            _btn("btnLayerAdd"),  # R1, слои: +a
            _pick(_C),
            _btn("btnLayerAdd"),  # R2, слои: +a +c
            _pick(_B),
            _btn("btnLayerAdd"),  # R3, слои: +a +c +b
            _SETTLE,
            _UNDO,  # снимает R3 -> [.., a, c]; выбранный «b» исчез
            _SETTLE,
            _snap("undone"),
            {"op": "key", "key": "ArrowRight", "target": "BODY"},
            {"op": "key", "key": "ArrowDown", "shift": True, "target": "BODY"},
            _SETTLE,
            _snap("arrows"),
            _UNDO,  # снимает R2 (если стрелки записей не писали) -> [.., a]
            _SETTLE,
            _snap("undo2"),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert [ly["name"] for ly in _eff(s["undone"])] == ["disk", "letter", "cap", "a", "c"], _eff(s["undone"])
    assert _eff(s["arrows"]) == _eff(s["undone"]), "стрелки без выбора ничего не сдвигают"
    assert s["arrows"]["layoutCount"] == s["undone"]["layoutCount"], (
        f"стрелки без выбора не запрашивают раскладку: {s['undone']['layoutCount']} -> {s['arrows']['layoutCount']}"
    )
    assert [ly["name"] for ly in _eff(s["undo2"])] == ["disk", "letter", "cap", "a"], (
        f"вторая «Отмена» должна снять R2 (a, c -> a); лишняя запись стрелки оставила бы 5 слоёв: {_eff(s['undo2'])!r}"
    )


def test_f2_stale_selection_name_does_not_revive_on_a_later_layer(start_pult) -> None:
    """F2 (RED до исправления): «Добавить a» -> «Отмена» -> слой `cap` переименован в `a`. Выбора нет, значит стрелка
    ничего не сдвигает, строка не подсвечена и раскладка не запрошена. Если `presetSelected` остался на исчезнувшем
    имени «a», переименование «оживляет» его на ЧУЖОМ слое (до исправления: offset -70 -> -69, +1 запрос раскладки,
    подсвечена строка `a`). Так наблюдается `presetSelected === null` — прямо снимок его не показывает."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            _SETTLE,
            _pick(_A),
            _btn("btnLayerAdd"),
            _SETTLE,
            _UNDO,
            _SETTLE,
            {"op": "set_field", "id": "layer2_name", "value": "a"},  # cap -> a: имя исчезнувшего слоя занято снова
            _SETTLE,
            _snap("renamed", ["layer2_name", "layer2_offset_x"]),
            {"op": "key", "key": "ArrowRight", "target": "BODY"},
            _SETTLE,
            _snap("arrow", ["layer2_name", "layer2_offset_x"]),
        ],
    )
    _assert_ran(out)
    r, a = out["snaps"]["renamed"], out["snaps"]["arrow"]
    assert r["fields"] == {"layer2_name": "a", "layer2_offset_x": "-70"}, (
        f"предусловие: cap переименован в a: {r['fields']!r}"
    )
    assert r["selected"] == [], f"само переименование ничего не выбирает: {r['selected']!r}"
    assert a["selected"] == [], f"выбора нет, а подсвечена строка {a['selected']!r} (устаревшее имя «a» ожило)"
    assert a["fields"] == r["fields"], (
        f"стрелка сдвинула слой, которого никто не выбирал: {r['fields']!r} -> {a['fields']!r}"
    )
    assert a["layoutCount"] == r["layoutCount"], (
        f"стрелка без выбора не запрашивает раскладку: {r['layoutCount']} -> {a['layoutCount']}"
    )


def test_f2_control_undo_keeps_selection_when_the_layer_survives(start_pult) -> None:
    """F2 контроль (зелёный и до исправления): выбрать disk, сдвинуть стрелкой (+1), «Отмена» -> сдвиг откатан,
    выбор СОХРАНЁН (подсвечен disk), и стрелка снова двигает именно его (+1 и один запрос раскладки)."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            _SETTLE,
            _click(_AT_DISK),
            {"op": "key", "key": "ArrowRight"},
            _SETTLE,
            _snap("shifted", ["layer0_offset_x"]),
            _UNDO,
            _SETTLE,
            _snap("undone", ["layer0_offset_x"]),
            {"op": "key", "key": "ArrowRight"},
            _SETTLE,
            _snap("again", ["layer0_offset_x"]),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert s["shifted"]["fields"] == {"layer0_offset_x": "1"}, (
        f"контроль: стрелка сдвинула выбранный disk: {s['shifted']['fields']!r}"
    )
    assert s["undone"]["fields"] == {"layer0_offset_x": "0"}, f"«Отмена» откатила сдвиг: {s['undone']['fields']!r}"
    assert s["undone"]["selected"] == ["disk"], f"слой остался, значит выбор сохранён: {s['undone']['selected']!r}"
    assert s["again"]["fields"] == {"layer0_offset_x": "1"}, (
        f"выбор рабочий: стрелка снова двигает disk: {s['again']['fields']!r}"
    )
    assert s["again"]["layoutCount"] == s["undone"]["layoutCount"] + 1, "ровно один запрос раскладки на стрелку"
