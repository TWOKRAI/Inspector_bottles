# -*- coding: utf-8 -*-
"""RED-приёмка R-5 — хвосты страницы редактора слоёв `pult_web` (а, б, г, д).

Независимый tester вслепую, worktree `r5-tester`, ветка `tests/r5-blind` на `9f751faf` (исправления нет).
Источник — только критерии лида из брифа R-5 (`plans/queue/defects.md`, строка R-5). Реализация страницы
(`plugin.py`) НЕ читалась; идиома сценариев взята из `test_acceptance_1_3h_c_fix.py`, `test_acceptance_1_3h_d_page.py`
и их общих помощников в `test_acceptance_1_3h_c_layers.py`.

Контракт, который пинит этот файл (своими словами)
====================================================
(а) Выбор принадлежит СЛОЮ (строке), а не строке-имени. Переименование выбранного слоя в форме выбор не сбрасывает
    и не переносит; «Отмена» возвращает слой на его место, и он остаётся выбранным; чужой слой, получивший
    прежнее имя выбранного, выбранным не становится. Стрелка двигает ровно выбранный слой.
(б) Два «Обновить список» подряд, ответ на ПЕРВЫЙ приходит ПОСЛЕ ответа на второй: страница показывает
    ВТОРОЙ ответ (пункты `<select>`, текст отказа списка) — запоздавший первый его не затирает.
(г) Пресет не загружен (`GET /api/preset` — отказ) + загрузка PNG, `sprite_put` ответил ok: в
    `#presetSpritesError` сказано, что файл СОХРАНЁН (по имени файла), но слой НЕ добавлен, потому что пресет не
    загружен; текст переживает обновление списка, которое запускает загрузка; слой не добавлен.
(д) Ошибка `FileReader`: `#presetSpritesError` начинается с «загрузка не удалась», запроса `sprite_put` нет,
    `input.value === ""`, фокус на канве.

Как это измеряется
------------------
Только наблюдаемое: значения полей формы, подсветка строк, тела запросов страницы, текст `#presetSpritesError`,
пункты `<select>`, `document.activeElement`. Имён JS-функций страницы тесты не знают.
Харнесс `page_offline.mjs` расширен аддитивно: `choose_file` понимает `readError` (FileReader отдаёт `error`, не
`load`) и пишет `out.picks` (значение контрола сразу после выбора); шаги `hold_fetch` / `release_fetch` удерживают
ответ на запрос к пути и отдают его позже (ответ «не по порядку»); в контекст страницы добавлен `AbortController`, а
`abort` сигнала отклоняет удержанный запрос.
Никакого `pytest.mark.timeout` (плагин не установлен): каждый блокирующий вызов харнесса ограничен своим дедлайном
(`wait_drawn` 2.5 с, `settle` 4 с, watchdog харнесса 20 с, `subprocess` 30 с).
"""

# ruff: noqa: F811  (start_pult — фикстура из соседнего файла: ре-импорт и параметр теста)

from __future__ import annotations

import json

import pytest

from Plugins.sim.pult_web.tests.test_acceptance_1_3h_c_layers import (  # noqa: F401  (start_pult — фикстура)
    _A,
    _AT_DISK,
    _C,
    _CLASS,
    _FILES,
    _INITIAL,
    _READY,
    _SETTLE,
    _SPRITES,
    _SPRITES_OK,
    _UNDO,
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

_SPRITES_PATH = "/api/preset/sprites"
_PUT = "/api/preset/sprite_put"
_KEY_RIGHT = {"op": "key", "key": "ArrowRight"}  # источник — канва (по умолчанию)
_SETTLED = {"op": "settle"}


def _rename(index: int, name: str) -> list[dict]:
    """Правка имени слоя в форме как в браузере: значение поля + `change` на самом поле + всплывший `change` на
    контейнере `#presetLayers` (харнесс сам не всплывает; тот же приём — в `test_hazards_1_3h_canvas.py`)."""
    return [
        {"op": "set_field", "id": f"layer{index}_name", "value": name},
        {"op": "fire_el", "id": "presetLayers", "type": "change"},
    ]


# --------------------------------------------------------------------------- #
# (а) выбор принадлежит слою                                                  #
# --------------------------------------------------------------------------- #
def test_a1_rename_undo_keeps_selection(start_pult) -> None:
    """(а1) Репро ревью 1: выбрать disk на канве, переименовать его в форме в `disk2`, «Отмена» -> слой снова `disk`
    на том же месте И всё ещё выбран: подсвечена его строка, а стрелка вправо двигает поле смещения именно disk.

    ЗЕЛЁНЫЙ уже до исправления (предсказывали красный): выбор хранится именем «disk», строка формы имени не меняет,
    а «Отмена» возвращает то же имя — совпадение по имени срабатывает случайно. Значит (а1) — страж, а красная
    часть «выбор переживает переименование» пинится в (а3), «выбор не переезжает на чужое имя» — в (а2)."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            _SETTLE,
            _click(_AT_DISK),
            *_rename(0, "disk2"),
            _SETTLE,
            _snap("renamed", ["layer0_name", "layer0_offset_x"]),
            _UNDO,
            _SETTLE,
            _snap("undone", ["layer0_name", "layer0_offset_x"]),
            _KEY_RIGHT,
            _SETTLE,
            _snap("arrow", ["layer0_name", "layer0_offset_x"]),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert s["renamed"]["fields"]["layer0_name"] == "disk2", f"предусловие: имя правлено: {s['renamed']['fields']!r}"
    assert _eff(s["undone"]) == _INITIAL, f"«Отмена» вернула слои как были: {_eff(s['undone'])!r}"
    assert s["undone"]["selected"] == ["disk"], (
        f"слой вернулся как disk на прежнее место, выбор должен остаться на нём: {s['undone']['selected']!r}"
    )
    assert s["arrow"]["fields"] == {"layer0_name": "disk", "layer0_offset_x": "1"}, (
        f"стрелка вправо должна сдвинуть выбранный disk (0 -> 1): {s['undone']['fields']!r} -> {s['arrow']['fields']!r}"
    )


def test_a2_undo_does_not_move_foreign_layer(start_pult) -> None:
    """(а2) Репро ревью 2: в форме letter -> `x`, disk -> `letter` (два `change` с всплытием), клик по disk на канве,
    «Отмена» -> выбран восстановленный disk; стрелка вправо двигает ТОЛЬКО его: смещение disk 0 -> 1, смещение соседа
    (слой 1, прежде `letter`) остаётся 60 (баг: 60 -> 61 — стрелка ушла на слой с занятым именем).

    Правка R-5 ит.3 (лид, по ревью ит.2 находка 2): после двух переименований добавлен `_SETTLE` перед кликом —
    клик должен попасть в раскладку с новыми именами; без ожидания это гонка с её ответом (флейк 1 из 5)."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            _SETTLE,
            *_rename(1, "x"),
            *_rename(0, "letter"),
            _SETTLE,
            _click(_AT_DISK),
            _UNDO,
            _SETTLE,
            _snap("undone", ["layer0_offset_x", "layer1_offset_x"]),
            _KEY_RIGHT,
            _SETTLE,
            _snap("arrow", ["layer0_offset_x", "layer1_offset_x"]),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert _eff(s["undone"]) == _INITIAL, f"предусловие: «Отмена» вернула все слои как были: {_eff(s['undone'])!r}"
    assert s["undone"]["fields"] == {"layer0_offset_x": "0", "layer1_offset_x": "60"}, s["undone"]["fields"]
    assert s["arrow"]["fields"] == {"layer0_offset_x": "1", "layer1_offset_x": "60"}, (
        f"стрелка должна сдвинуть только disk (слой 0), а соседа не трогать: "
        f"{s['undone']['fields']!r} -> {s['arrow']['fields']!r}"
    )


def test_a2_undo_highlights_restored_layer_not_the_foreign_one(start_pult) -> None:
    """(а2, подсветка) Тот же сценарий: после «Отмены» подсвечена ровно одна строка — строка восстановленного disk
    (её имя `disk`), а не строка слоя 1, который в ходе правок носил имя `letter`."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            _SETTLE,
            *_rename(1, "x"),
            *_rename(0, "letter"),
            _click(_AT_DISK),
            _UNDO,
            _SETTLE,
            _snap("undone"),
        ],
    )
    _assert_ran(out)
    assert out["snaps"]["undone"]["rows"] == ["disk", "letter", "cap"], (
        f"предусловие: строки формы вернулись: {out['snaps']['undone']['rows']!r}"
    )
    assert out["snaps"]["undone"]["selected"] == ["disk"], (
        f"подсвечена должна быть строка disk, а не чужая: {out['snaps']['undone']['selected']!r}"
    )


def test_a3_rename_keeps_selection(start_pult) -> None:
    """(а3) Выбранный слой переименован в форме (без «Отмены»): он остаётся выбранным (подсвечена ровно одна
    строка), и стрелка вправо двигает ИМЕННО его (0 -> 1), соседей не трогает."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            _SETTLE,
            _click(_AT_DISK),
            _snap("picked"),
            *_rename(0, "disk2"),
            _SETTLE,
            _snap("renamed", ["layer0_offset_x", "layer1_offset_x", "layer2_offset_x"]),
            _KEY_RIGHT,
            _SETTLE,
            _snap("arrow", ["layer0_offset_x", "layer1_offset_x", "layer2_offset_x"]),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert s["picked"]["selected"] == ["disk"], f"контроль: клик по канве выбрал disk: {s['picked']['selected']!r}"
    assert len(s["renamed"]["selected"]) == 1, (
        f"переименование не должно снимать выбор: подсвечено {s['renamed']['selected']!r}"
    )
    assert s["arrow"]["fields"] == {"layer0_offset_x": "1", "layer1_offset_x": "60", "layer2_offset_x": "-70"}, (
        f"стрелка должна сдвинуть переименованный выбранный слой (слой 0): "
        f"{s['renamed']['fields']!r} -> {s['arrow']['fields']!r}"
    )


def test_a4_guard_add_then_undo_leaves_nothing_selected(start_pult) -> None:
    """(а4, страж, зелёный и до исправления) «Добавить» a.png -> слой выбран (контроль); «Отмена» -> слой убран,
    выбора нет."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [_READY, _SETTLE, _pick(_A), _btn("btnLayerAdd"), _SETTLE, _snap("added"), _UNDO, _SETTLE, _snap("undone")],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert s["added"]["selected"] == ["a"], f"контроль: «Добавить» выбрал новый слой: {s['added']['selected']!r}"
    assert [ly["name"] for ly in _eff(s["added"])] == ["disk", "letter", "cap", "a"], _eff(s["added"])
    assert _eff(s["undone"]) == _INITIAL, f"«Отмена» убрала добавленный слой: {_eff(s['undone'])!r}"
    assert s["undone"]["selected"] == [], f"добавленного слоя нет, выбирать нечего: {s['undone']['selected']!r}"


def test_a4_guard_up_then_undo_keeps_same_layer_selected(start_pult) -> None:
    """(а4, страж, зелёный и до исправления) Выбрать disk, «Выше» -> disk переехал к концу (порядок letter, disk,
    cap), выбран он же; «Отмена» -> порядок прежний, выбран тот же слой (по имени disk)."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            _SETTLE,
            _click(_AT_DISK),
            _btn("btnLayerUp"),
            _SETTLE,
            _snap("up"),
            _UNDO,
            _SETTLE,
            _snap("undone"),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert [ly["name"] for ly in _eff(s["up"])] == ["letter", "disk", "cap"], (
        f"контроль: «Выше» переставила disk: {_eff(s['up'])!r}"
    )
    assert s["up"]["selected"] == ["disk"], f"контроль: после «Выше» выбран тот же disk: {s['up']['selected']!r}"
    assert [ly["name"] for ly in _eff(s["undone"])] == ["disk", "letter", "cap"], _eff(s["undone"])
    assert s["undone"]["selected"] == ["disk"], f"после «Отмены» выбран тот же слой: {s['undone']['selected']!r}"


# --------------------------------------------------------------------------- #
# (б) ответ списка спрайтов приходит не по порядку                            #
# --------------------------------------------------------------------------- #
_REFUSAL = {"status": "error", "code": "io_error", "message": "каталога нет: data/line_sim"}
_STALE_OK = {**_SPRITES_OK, "files": [{"path": "a.png", "sprite_source": _A}]}
_FRESH_OK = {**_SPRITES_OK, "files": [{"path": "c.png", "sprite_source": _C}]}


def _refresh_race(port: int) -> dict:
    """Загрузка страницы, два «Обновить список» подряд; ответ на ПЕРВЫЙ удержан и отдан страницей ПОСЛЕ второго.
    Снимки: `fresh_only` — второй ответ дошёл, первый ещё удержан; `after` — первый отдан."""
    out = _run_canvas(
        port,
        [
            _READY,
            _SETTLE,
            {"op": "hold_fetch", "path": _SPRITES_PATH},
            _btn("btnSpritesRefresh"),
            {"op": "sleep", "ms": 200},  # первый запрос дошёл до сервера (и взял первый ответ из очереди)
            _btn("btnSpritesRefresh"),
            _SETTLED,
            _snap("fresh_only"),
            {"op": "release_fetch", "path": _SPRITES_PATH, "index": 0},
            {"op": "sleep", "ms": 200},
            _snap("after"),
        ],
    )
    _assert_ran(out)
    posts = [e for e in out["fetchLog"] if e["path"] == _SPRITES_PATH and e["method"] == "POST"]
    assert len(posts) == 3, f"загрузка + два «Обновить список»: {posts!r}"
    assert posts[1].get("held") is True and not posts[2].get("held"), f"удержан ровно первый из двух: {posts!r}"
    return out


def _option_values(snap: dict) -> list[str]:
    return sorted(o["value"] for o in snap["sel"]["options"])


def test_b_stale_success_ignored(start_pult) -> None:
    """(б) Запоздавший УСПЕШНЫЙ ответ первого «Обновить» (только a.png) не затирает свежий успешный второго
    (только c.png): в списке c.png и class:// и до, и после прихода первого ответа."""
    stand = _stand(start_pult, _INITIAL, sprites_replies=[_SPRITES_OK, _STALE_OK, _FRESH_OK])
    out = _refresh_race(stand.port)
    s = out["snaps"]
    assert _option_values(s["fresh_only"]) == sorted([_C, _CLASS]), (
        f"контроль: второй ответ показан, пока первый удержан: {s['fresh_only']['sel']['options']!r}"
    )
    assert _option_values(s["after"]) == sorted([_C, _CLASS]), (
        f"запоздавший первый ответ затёр второй: {s['after']['sel']['options']!r}"
    )


def test_b_stale_error_ignored(start_pult) -> None:
    """(б) Запоздавший ОТКАЗ первого «Обновить» не затирает свежий успех второго: список — по второму ответу
    (c.png и class://), текст отказа пуст — и до, и после прихода первого ответа."""
    stand = _stand(start_pult, _INITIAL, sprites_replies=[_SPRITES_OK, _REFUSAL, _FRESH_OK])
    out = _refresh_race(stand.port)
    s = out["snaps"]
    assert s["fresh_only"]["spritesError"].strip() == "", (
        f"контроль: второй (успешный) ответ показан, текста отказа нет: {s['fresh_only']['spritesError']!r}"
    )
    assert _option_values(s["fresh_only"]) == sorted([_C, _CLASS]), s["fresh_only"]["sel"]["options"]
    assert s["after"]["spritesError"].strip() == "", (
        f"запоздавший отказ первого ответа показан поверх свежего успеха: {s['after']['spritesError']!r}"
    )
    assert _option_values(s["after"]) == sorted([_C, _CLASS]), (
        f"после запоздавшего отказа список не должен меняться: {s['after']['sel']['options']!r}"
    )


def test_b_stale_success_does_not_hide_fresh_error(start_pult) -> None:
    """(б, зеркало) Первый ответ — успех (удержан), второй — отказ: после прихода первого текст отказа второго
    остаётся виден (запоздавший успех не стирает его)."""
    stand = _stand(start_pult, _INITIAL, sprites_replies=[_SPRITES_OK, _STALE_OK, _REFUSAL])
    out = _refresh_race(stand.port)
    s = out["snaps"]
    assert "data/line_sim" in s["fresh_only"]["spritesError"], (
        f"контроль: отказ второго ответа показан, пока первый удержан: {s['fresh_only']['spritesError']!r}"
    )
    assert "data/line_sim" in s["after"]["spritesError"], (
        f"запоздавший успех стёр текст свежего отказа: {s['after']['spritesError']!r}"
    )


# --------------------------------------------------------------------------- #
# (г) загрузка PNG, пока пресет не загружен                                   #
# --------------------------------------------------------------------------- #
_UP_SRC = "../../data/line_sim/up.png"
_UP_DATA_URL = "data:image/png;base64,QUJD"  # base64("ABC")
_PUT_OK = {"status": "ok", "file": {"path": "up.png", "sprite_source": _UP_SRC}}
_SPRITES_WITH_UP = {**_SPRITES_OK, "files": [*_FILES, {"path": "up.png", "sprite_source": _UP_SRC}]}
_INPUT = "presetSpriteFile"


@pytest.fixture(autouse=True)
def _layout_knows_uploaded_sprite(monkeypatch: pytest.MonkeyPatch) -> None:
    """Двойник раскладки отвечает `invalid` на неизвестный спрайт — загруженный файл ему известен."""
    monkeypatch.setitem(_SPRITES, _UP_SRC, _SPRITES["sprites/a.png"])


def _choose(*, read_error: bool = False) -> dict:
    step = {"op": "choose_file", "id": _INPUT, "name": "up.png", "dataUrl": _UP_DATA_URL}
    if read_error:
        step["readError"] = True
    return step


def _put_posts(out: dict) -> list[dict]:
    return [e for e in out["fetchLog"] if e["path"] == _PUT]


def _upload_without_preset(start_pult) -> dict:
    """Пресет не загружен (`preset.get` — отказ), `sprite_put` (подмена) отвечает ok; выбран `up.png`."""
    stand = _stand(start_pult, _INITIAL, sprites_replies=[_SPRITES_OK, _SPRITES_WITH_UP])
    stand.scene.responses["preset.get"] = {"status": "error", "code": "unavailable", "message": "сцена не отвечает"}
    out = _run_canvas(
        stand.port,
        [
            {"op": "stub_fetch", "path": _PUT, "status": 200, "json": _PUT_OK},
            {"op": "sleep", "ms": 500},  # начальная загрузка (её отказ) отработала
            {"op": "focus_el", "id": _INPUT},
            _snap("before", [_INPUT]),
            _choose(),
            _SETTLED,
            _snap("after", [_INPUT]),
        ],
    )
    assert out["aborted"] is None, f"сценарий прерван: {out['aborted']!r}"
    assert len(_put_posts(out)) == 1, f"контроль: загрузка была предпринята и дошла до sprite_put: {out['fetchLog']!r}"
    return out


def test_g_upload_without_preset_explains(start_pult) -> None:
    """(г) Пресет не загружен, файл сохранён (`sprite_put` ok): `#presetSpritesError` называет файл по имени и
    говорит, что слой НЕ добавлен, потому что пресет не загружен."""
    out = _upload_without_preset(start_pult)
    text = out["snaps"]["after"]["spritesError"]
    low = text.lower()
    assert "up.png" in text, f"в тексте должно быть имя сохранённого файла: {text!r}"
    assert "не добавлен" in low, f"в тексте должно быть сказано, что слой не добавлен: {text!r}"
    assert "пресет" in low, f"в тексте должна быть названа причина — пресет не загружен: {text!r}"


def test_g_message_survives_the_list_refresh_the_upload_triggers(start_pult) -> None:
    """(г) Загрузка после ok перезапрашивает список спрайтов (якорь: запрос ПОСЛЕ `sprite_put` был), а текст
    объяснения в `#presetSpritesError` после этого обновления не стёрт и новый файл уже в списке."""
    out = _upload_without_preset(start_pult)
    log = out["fetchLog"]
    put_at = next(i for i, e in enumerate(log) if e["path"] == _PUT)
    refreshed_after = [
        i for i, e in enumerate(log) if e["path"] == _SPRITES_PATH and e["method"] == "POST" and i > put_at
    ]
    assert refreshed_after, f"якорь: после загрузки список спрайтов должен быть запрошен заново: {log!r}"
    after = out["snaps"]["after"]
    assert _UP_SRC in [o["value"] for o in after["sel"]["options"]], (
        f"якорь: обновление списка дошло до страницы, файл в списке: {after['sel']['options']!r}"
    )
    assert "up.png" in after["spritesError"], f"текст стёрт обновлением списка: {after['spritesError']!r}"


def test_g_guard_upload_without_preset_adds_no_layer(start_pult) -> None:
    """(г, страж) Пресета нет — слой не добавляется и раскладку никто не просит (якорь: загрузка дошла до
    `sprite_put`, и после неё список спрайтов перезапрошен)."""
    out = _upload_without_preset(start_pult)
    after = out["snaps"]["after"]
    assert not after["layers"], f"без пресета слоёв быть не должно: {after['layers']!r}"
    assert after["layoutCount"] == 0, f"раскладку без пресета не запрашивают: {after['layoutCount']}"


# --------------------------------------------------------------------------- #
# (д) ошибка чтения файла                                                     #
# --------------------------------------------------------------------------- #
def _upload_with_read_error(start_pult) -> dict:
    stand = _stand(start_pult, _INITIAL, sprites_replies=[_SPRITES_OK])
    out = _run_canvas(
        stand.port,
        [
            _READY,
            _SETTLE,
            {"op": "focus_el", "id": _INPUT},
            _snap("before", [_INPUT]),
            _choose(read_error=True),
            _SETTLED,
            _snap("after", [_INPUT]),
        ],
    )
    _assert_ran(out)
    # якорь: файл действительно выбран (контрол получил значение) — значит, сброс value ниже сделала страница
    assert out["picks"] == [{"id": _INPUT, "name": "up.png", "value": "C:\\fakepath\\up.png"}], out["picks"]
    return out


def test_d_read_error_shows_message(start_pult) -> None:
    """(д) `FileReader` отдал ошибку -> текст в `#presetSpritesError` начинается с «загрузка не удалась»."""
    out = _upload_with_read_error(start_pult)
    before, after = out["snaps"]["before"], out["snaps"]["after"]
    assert before["spritesError"].strip() == "", f"контроль: до выбора текста нет: {before['spritesError']!r}"
    assert after["spritesError"].strip().lower().startswith("загрузка не удалась"), (
        f"ошибка чтения файла не показана: {after['spritesError']!r}"
    )


def test_d_read_error_sends_no_sprite_put(start_pult) -> None:
    """(д) При ошибке чтения запроса `sprite_put` нет (якорь: страница отреагировала — текст ошибки показан)."""
    out = _upload_with_read_error(start_pult)
    assert out["snaps"]["after"]["spritesError"].strip() != "", "якорь: страница обработала ошибку чтения"
    assert _put_posts(out) == [], f"при ошибке чтения sprite_put уходить не должен: {_put_posts(out)!r}"


def test_d_read_error_clears_input_value(start_pult) -> None:
    """(д) После ошибки чтения `input.value === ""` (тот же файл можно выбрать снова)."""
    out = _upload_with_read_error(start_pult)
    assert out["snaps"]["after"]["fields"][_INPUT] == "", (
        f"value контрола не сброшен: {out['snaps']['after']['fields'][_INPUT]!r}"
    )


def test_d_read_error_moves_focus_to_canvas(start_pult) -> None:
    """(д) После ошибки чтения фокус на `#presetCanvas` (до выбора — на контроле), новые вызовы `focus()` канвы
    все с `{ preventScroll: true }`."""
    out = _upload_with_read_error(start_pult)
    before, after = out["snaps"]["before"], out["snaps"]["after"]
    assert before["active"] == _INPUT, f"контроль: до выбора фокус на контроле: {before['active']!r}"
    assert after["active"] == "presetCanvas", f"фокус после ошибки чтения: {after['active']!r}"
    new_calls = after["focusCalls"][len(before["focusCalls"]) :]
    assert new_calls and all(c == {"preventScroll": True} for c in new_calls), (
        f"focus() канвы с preventScroll: {new_calls!r}"
    )


def test_harness_selfcheck_hold_fetch_defers_and_releases(start_pult) -> None:
    """Самопроверка харнесса (страницу не оценивает): удержанный ответ доходит только после `release_fetch`.
    Иначе (б) могло бы быть зелёным/красным от самого харнесса. Один «Обновить», ответ отличается от стартового."""
    stand = _stand(start_pult, _INITIAL, sprites_replies=[_SPRITES_OK, _FRESH_OK])
    out = _run_canvas(
        stand.port,
        [
            _READY,
            _SETTLE,
            {"op": "hold_fetch", "path": _SPRITES_PATH},
            _btn("btnSpritesRefresh"),
            {"op": "sleep", "ms": 400},
            _snap("held"),
            {"op": "release_fetch", "path": _SPRITES_PATH, "index": 0},
            {"op": "sleep", "ms": 200},
            _snap("released"),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert len(_option_values(s["held"])) == len(_FILES) + 1, (
        f"пока ответ удержан, список прежний: {s['held']['sel']['options']!r}"
    )
    assert _option_values(s["released"]) == sorted([_C, _CLASS]), (
        f"после release_fetch список по новому ответу: {s['released']['sel']['options']!r}"
    )
    assert json.dumps(out["fetchLog"]).count('"held": true') == 1
