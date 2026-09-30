# -*- coding: utf-8 -*-
"""Hazard-тесты автора R-5 (а) — выбор слоя принадлежит СТРОКЕ формы.

Автор пишет их про внутренние места механизма, которые слепой tester (`test_acceptance_r5_page.py`) не видел:
выбор хранится парой «имя + строка»; действия (стрелка, «Удалить», «Выше») идут по СТРОКЕ, а не по поиску имени, а
запись стека «Отмена» помнит род правки (`reorders`) и строку выбора до операции над составом. Ломаются эти места
тихо: подсветка/стрелка уходят на ЧУЖОЙ слой, ошибок в консоли нет.

Идиома та же, что в приёмке: харнесс `page_offline.mjs`, только наблюдаемое (поля формы, подсветка, тела запросов).
Никакого `pytest.mark.timeout` (плагин не установлен) — каждый блокирующий вызов харнесса ограничен его дедлайнами.
"""

# ruff: noqa: F811  (start_pult — фикстура из соседнего файла: ре-импорт и параметр теста)

from __future__ import annotations

import json
import time

from Plugins.sim.pult_web.tests.test_acceptance_1_3h_c_layers import (  # noqa: F401  (start_pult — фикстура)
    _A,
    _AT_DISK,
    _AT_LETTER,
    _C,
    _CLASS,
    _INITIAL,
    _READY,
    _SETTLE,
    _SPRITES_OK,
    _UNDO,
    _assert_ran,
    _btn,
    _click,
    _eff,
    _pick,
    _snap,
    _stand,
    _run_canvas,
    start_pult,
)

_KEY_RIGHT = {"op": "key", "key": "ArrowRight"}  # источник — канва (по умолчанию)
_FIELDS = ["layer0_offset_x", "layer1_offset_x", "layer2_offset_x"]  # порядок _INITIAL: disk 0, letter 60, cap -70


def _rename(index: int, name: str) -> list[dict]:
    """Правка имени слоя в форме как в браузере: значение поля + `change` на поле + всплывший `change` на контейнере."""
    return [
        {"op": "set_field", "id": f"layer{index}_name", "value": name},
        {"op": "fire_el", "id": "presetLayers", "type": "change"},
    ]


def test_h1_up_then_rename_other_layer_then_undo_keeps_moved_layer_selected(start_pult) -> None:
    """(h1) «Выше» на выбранном disk (порядок letter, disk, cap; disk — строка 1), затем правка имени ДРУГОГО слоя
    (строка 0), «Отмена» -> выбран по-прежнему disk (строка 1), стрелка двигает его, а не соседа.

    Что ломает: «Отмена» правки полей берёт строку из СТАРОГО порядка (до «Выше», строка 0 -> letter) или из
    `presetSelectedRow` уже после `pop`, когда он относится к другому состоянию; либо выбор по имени, переехавшему
    вместе с переименованием чужой строки. Тогда стрелка сдвинула бы letter (слой 0)."""
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
            *_rename(0, "zz"),
            _SETTLE,
            _UNDO,
            _SETTLE,
            _snap("undone", _FIELDS),
            _KEY_RIGHT,
            _SETTLE,
            _snap("arrow", _FIELDS),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert [ly["name"] for ly in _eff(s["up"])] == ["letter", "disk", "cap"], f"предусловие: {_eff(s['up'])!r}"
    assert [ly["name"] for ly in _eff(s["undone"])] == ["letter", "disk", "cap"], (
        f"«Отмена» вернула только переименование, порядок остался: {_eff(s['undone'])!r}"
    )
    assert s["undone"]["selected"] == ["disk"], f"выбран должен остаться disk: {s['undone']['selected']!r}"
    # строка 0 — letter (60), строка 1 — disk (0): двигаться должна строка 1
    assert s["undone"]["fields"] == {"layer0_offset_x": "60", "layer1_offset_x": "0", "layer2_offset_x": "-70"}
    assert s["arrow"]["fields"] == {"layer0_offset_x": "60", "layer1_offset_x": "1", "layer2_offset_x": "-70"}, (
        f"стрелка должна сдвинуть disk (строка 1): {s['undone']['fields']!r} -> {s['arrow']['fields']!r}"
    )


def test_h2_delete_selected_then_undo_selects_the_restored_layer_again(start_pult) -> None:
    """(h2) Удалить выбранный disk, «Отмена» -> слой вернулся И выбран снова (строка 0), стрелка двигает именно его.

    СМЫСЛ ИЗМЕНЁН ПО ДИЗАЙНУ (итерация 2 R-5, решение лида): в итерации 1 тест требовал «выбора нет»; теперь запись
    «Отмена» операции над составом помнит строку выбора ДО операции, и «Отмена» её возвращает — выбор, каким он был
    прямо перед удалением. Чужого слоя это не задевает: строка берётся из записи, а не ищется по имени.

    Что ломает: «Отмена» не восстанавливает строку из записи (выбор остаётся пустым) либо берёт её из
    `presetSelectedRow` уже после `pop`; либо «Удалить» не сбрасывает выбор (контроль `deleted.selected == []`)."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            _SETTLE,
            _click(_AT_DISK),
            _btn("btnLayerDelete"),
            _SETTLE,
            _snap("deleted"),
            _UNDO,
            _SETTLE,
            _snap("undone", _FIELDS),
            _KEY_RIGHT,
            _SETTLE,
            _snap("arrow", _FIELDS),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert [ly["name"] for ly in _eff(s["deleted"])] == ["letter", "cap"], f"предусловие: {_eff(s['deleted'])!r}"
    assert s["deleted"]["selected"] == [], f"после удаления выбирать нечего: {s['deleted']['selected']!r}"
    assert _eff(s["undone"]) == _INITIAL, f"«Отмена» вернула слой: {_eff(s['undone'])!r}"
    assert s["undone"]["selected"] == ["disk"], f"вернувшийся слой выбран снова: {s['undone']['selected']!r}"
    assert s["undone"]["fields"] == {"layer0_offset_x": "0", "layer1_offset_x": "60", "layer2_offset_x": "-70"}
    assert s["arrow"]["fields"] == {"layer0_offset_x": "1", "layer1_offset_x": "60", "layer2_offset_x": "-70"}, (
        f"стрелка должна сдвинуть вернувшийся disk (строка 0): {s['undone']['fields']!r} -> {s['arrow']['fields']!r}"
    )


def test_h3_rename_then_add_then_undo_twice_restores_the_selection_row(start_pult) -> None:
    """(h3) Выбран disk (строка 0); переименован в disk2; «Добавить» a.png (выбран новый слой `a`, строка 3);
    «Отмена» №1 -> слои до «Добавить» (disk2, letter, cap), выбрана строка 0 (как до операции); «Отмена» №2 (правка
    полей — строки те же, текущая строка 0 остаётся) -> слои как были (disk, letter, cap), выбран disk, и стрелка
    двигает именно его, а не соседа.

    СМЫСЛ ИЗМЕНЁН ПО ДИЗАЙНУ (итерация 2 R-5, тот же дизайн, что у h2): в итерации 1 после «Отмен» ожидалось
    «выбора нет»; теперь запись «Добавить» помнит строку 0, а правка полей строку не трогает.

    Что ломает: восстановление по имени (после №2 имя `disk2` исчезло бы — выбор потерян) либо строка из
    `presetSelectedRow`, не обновлённого записью (после №1 остался бы выбранным призрачный индекс 3)."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            _SETTLE,
            _click(_AT_DISK),
            *_rename(0, "disk2"),
            _SETTLE,
            _pick(_A),
            _btn("btnLayerAdd"),
            _SETTLE,
            _snap("added"),
            _UNDO,
            _SETTLE,
            _snap("undo1"),
            _UNDO,
            _SETTLE,
            _snap("undo2", _FIELDS),
            _KEY_RIGHT,
            _SETTLE,
            _snap("arrow", _FIELDS),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert [ly["name"] for ly in _eff(s["added"])] == ["disk2", "letter", "cap", "a"], _eff(s["added"])
    assert s["added"]["selected"] == ["a"], f"контроль: выбран добавленный слой: {s['added']['selected']!r}"
    assert [ly["name"] for ly in _eff(s["undo1"])] == ["disk2", "letter", "cap"], _eff(s["undo1"])
    assert s["undo1"]["selected"] == ["disk2"], f"выбор как до «Добавить» (строка 0): {s['undo1']['selected']!r}"
    assert _eff(s["undo2"]) == _INITIAL, f"вторая «Отмена» вернула исходные слои: {_eff(s['undo2'])!r}"
    assert s["undo2"]["selected"] == ["disk"], f"выбран disk (строка 0): {s['undo2']['selected']!r}"
    assert s["arrow"]["fields"] == {"layer0_offset_x": "1", "layer1_offset_x": "60", "layer2_offset_x": "-70"}, (
        f"стрелка должна сдвинуть disk (строка 0): {s['undo2']['fields']!r} -> {s['arrow']['fields']!r}"
    )


def test_h4_rename_then_up_then_undo_twice_never_selects_a_foreign_layer(start_pult) -> None:
    """(h4) Выбран disk; переименован в disk2; «Выше» (операция над составом при правленной форме; выбор — по
    имени disk2, строка 1); «Отмена» дважды -> слои как были. Выбор либо пуст, либо на самом disk; чужой слой
    (letter, cap) выбран быть НЕ может, и стрелка не двигает их.

    Известный предел (не свойство, а честная граница): вторая «Отмена» откатывает переименование, имя `disk2`
    исчезает и выбор сбрасывается — выбор ТЕРЯЕТСЯ, но не уходит не туда. Если когда-нибудь выбор станет
    переживать и этот случай, тест останется зелёным (допускает оба исхода) — так и задумано.

    Что ломает: восстановление выбора по строке в ветке, где форма была синхронна: строка 1 после второй «Отмены»
    указала бы на letter."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            _SETTLE,
            _click(_AT_DISK),
            *_rename(0, "disk2"),
            _SETTLE,
            _btn("btnLayerUp"),
            _SETTLE,
            _snap("up"),
            _UNDO,
            _SETTLE,
            _UNDO,
            _SETTLE,
            _snap("undo2", _FIELDS),
            _KEY_RIGHT,
            _SETTLE,
            _snap("arrow", _FIELDS),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert [ly["name"] for ly in _eff(s["up"])] == ["letter", "disk2", "cap"], f"предусловие: {_eff(s['up'])!r}"
    assert _eff(s["undo2"]) == _INITIAL, f"обе «Отмены» вернули исходные слои: {_eff(s['undo2'])!r}"
    assert s["undo2"]["selected"] in ([], ["disk"]), f"выбран чужой слой: {s['undo2']['selected']!r}"
    before, after = s["undo2"]["fields"], s["arrow"]["fields"]
    moved = {k: (before[k], after[k]) for k in _FIELDS if before[k] != after[k]}
    assert set(moved) <= {"layer0_offset_x"}, f"стрелка сдвинула чужой слой: {moved!r}"


def test_h5_stale_network_failure_does_not_overwrite_fresh_list(start_pult) -> None:
    """(h5) Первый «Обновить список» удержан (`hold_fetch`), второй получает свежий список (только c.png);
    затем удержанный первый запрос ОТКЛОНЯЕТСЯ сетью (сервер рвёт соединение, `fetch` -> reject, ответа нет
    вообще — ветка `.catch` страницы): текст «список спрайтов не получен» не появляется, список остаётся вторым.

    Как достигнуто без правки харнесса: обработчик `preset.sprites` двойника на втором вызове (первый «Обновить»)
    бросает исключение — `http.server` закрывает сокет без ответа, `real`-fetch харнесса отклоняется, а страница
    узнаёт об этом лишь по `release_fetch` (после свежего ответа второго запроса).

    Что ломает: убрать `if (seq !== presetSpritesSeq) return;` из `.catch` `presetLoadSprites` — запоздавший обрыв
    старого запроса пишет отказ поверх свежего успеха (акцептанс (б) это не ловит: там отказ приходит ТЕЛОМ ответа,
    через `.then`, а не отклонением промиса)."""
    fresh = {**_SPRITES_OK, "files": [{"path": "c.png", "sprite_source": _C}]}
    stand = _stand(start_pult, _INITIAL, sprites_replies=[_SPRITES_OK, fresh])
    calls = {"n": 0}

    def sprites(args: dict) -> dict:
        calls["n"] += 1
        if calls["n"] == 2:  # первый «Обновить»: соединение рвётся без ответа
            raise RuntimeError("обрыв: сервер не ответил")
        return json.loads(json.dumps(fresh if calls["n"] > 2 else _SPRITES_OK))

    stand.layers.handlers["preset.sprites"] = sprites
    out = _run_canvas(
        stand.port,
        [
            _READY,
            _SETTLE,
            {"op": "hold_fetch", "path": "/api/preset/sprites"},
            _btn("btnSpritesRefresh"),
            {"op": "sleep", "ms": 200},  # первый запрос дошёл до сервера (и оборвался)
            _btn("btnSpritesRefresh"),
            {"op": "settle"},
            _snap("fresh_only"),
            {"op": "release_fetch", "path": "/api/preset/sprites", "index": 0},
            {"op": "sleep", "ms": 200},
            _snap("after"),
        ],
    )
    _assert_ran(out)
    assert calls["n"] == 3, f"загрузка + два «Обновить список»: {calls['n']}"
    for key in ("fresh_only", "after"):
        snap = out["snaps"][key]
        assert sorted(o["value"] for o in snap["sel"]["options"]) == sorted([_C, _CLASS]), (
            f"[{key}] список должен быть вторым (c.png + class://): {snap['sel']['options']!r}"
        )
        assert "список спрайтов не получен" not in snap["spritesError"], (
            f"[{key}] запоздавший обрыв показан поверх свежего списка: {snap['spritesError']!r}"
        )


_OFF3 = {"layer0_offset_x": "0", "layer1_offset_x": "60", "layer2_offset_x": "-70"}


def _offs(a: str, b: str, c: str) -> dict:
    return {"layer0_offset_x": a, "layer1_offset_x": b, "layer2_offset_x": c}


def test_h6_swap_arrow_undo_twice_moves_the_clicked_layer(start_pult) -> None:
    """(h6) Выбран letter (строка 1); имена строк 0/1 обменяны на x/disk; стрелка сдвигает строку 1 (60 -> 61);
    «Отмена» (стрелка), «Отмена» (правка имён) -> имена исходные, выбран по-прежнему letter (строка 1), и стрелка
    двигает letter: 60 -> 61, а диск (строка 0, чьё имя занял бы поиск по имени `disk`) остаётся на 0.

    Что ломает: эвристика «правлена ли форма» (`presetDirty`) — после стрелки форма синхронна, запись правки
    ПОЛЕЙ разбирается веткой «по имени», и имя `disk` находит ЧУЖОЙ слой (строку 0)."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            _SETTLE,
            _click(_AT_LETTER),
            *_rename(0, "x"),
            *_rename(1, "disk"),
            _SETTLE,
            _KEY_RIGHT,
            _SETTLE,
            _snap("arrow", _FIELDS),
            _UNDO,
            _SETTLE,
            _UNDO,
            _SETTLE,
            _snap("undo2", _FIELDS),
            _KEY_RIGHT,
            _SETTLE,
            _snap("arrow2", _FIELDS),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert s["arrow"]["fields"] == _offs("0", "61", "-70"), f"предусловие: стрелка двигает строку 1: {s['arrow']!r}"
    assert _eff(s["undo2"]) == _INITIAL, f"обе «Отмены» вернули исходные слои: {_eff(s['undo2'])!r}"
    assert s["undo2"]["selected"] == ["letter"], f"выбран должен остаться letter: {s['undo2']['selected']!r}"
    assert s["arrow2"]["fields"] == _offs("0", "61", "-70"), (
        f"стрелка должна сдвинуть letter (строка 1), не disk: {s['undo2']['fields']!r} -> {s['arrow2']['fields']!r}"
    )


def test_h7_swap_save_undo_moves_the_clicked_layer(start_pult) -> None:
    """(h7) Выбран letter (строка 1); имена строк 0/1 обменяны на x/disk; «Сохранить» (форма синхронна); «Отмена» ->
    исходные имена, выбран letter (строка 1), стрелка двигает letter (60 -> 61), disk остаётся на 0.

    Что ломает: после «Сохранить» `presetDirty=false`, и «Отмена» правки полей уходит в ветку «по имени»: `disk`
    находится в восстановленном состоянии на строке 0."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            _SETTLE,
            _click(_AT_LETTER),
            *_rename(0, "x"),
            *_rename(1, "disk"),
            _SETTLE,
            _btn("btnPresetSave"),
            _SETTLE,
            _UNDO,
            _SETTLE,
            _snap("undo", _FIELDS),
            _KEY_RIGHT,
            _SETTLE,
            _snap("arrow", _FIELDS),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert len(stand.commits()) == 1, f"предусловие: «Сохранить» отправил ровно один commit: {stand.commits()!r}"
    assert _eff(s["undo"]) == _INITIAL, f"«Отмена» вернула исходные имена: {_eff(s['undo'])!r}"
    assert s["undo"]["selected"] == ["letter"], f"выбран должен остаться letter: {s['undo']['selected']!r}"
    assert s["arrow"]["fields"] == _offs("0", "61", "-70"), (
        f"стрелка должна сдвинуть letter (строка 1): {s['undo']['fields']!r} -> {s['arrow']['fields']!r}"
    )


def test_h8_rename_save_undo_keeps_selection(start_pult) -> None:
    """(h8) Выбран disk (строка 0); переименован в disk2; «Сохранить»; «Отмена» -> имя вернулось, выбран disk
    (подсвечена строка 0), стрелка двигает его.

    Что ломает: «Отмена» после «Сохранить» ищет выбранное имя `disk2` в восстановленном состоянии — его там нет,
    выбор молча сбрасывается."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            _SETTLE,
            _click(_AT_DISK),
            *_rename(0, "disk2"),
            _SETTLE,
            _btn("btnPresetSave"),
            _SETTLE,
            _UNDO,
            _SETTLE,
            _snap("undo", _FIELDS),
            _KEY_RIGHT,
            _SETTLE,
            _snap("arrow", _FIELDS),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert _eff(s["undo"]) == _INITIAL, f"«Отмена» вернула имя: {_eff(s['undo'])!r}"
    assert s["undo"]["selected"] == ["disk"], f"выбор должен пережить «Отмену»: {s['undo']['selected']!r}"
    assert s["arrow"]["fields"] == _offs("1", "60", "-70"), (
        f"стрелка должна сдвинуть disk: {s['undo']['fields']!r} -> {s['arrow']['fields']!r}"
    )


def test_h9_rename_drag_undo_twice_keeps_selection(start_pult) -> None:
    """(h9) Выбран disk; переименован в disk2; перетащен мышью (+10 px); «Отмена» (перетаскивание) -> выбран disk2;
    «Отмена» (переименование) -> имя disk, и выбор СОХРАНЁН (подсвечена строка 0).

    Что ломает: после перетаскивания форма синхронна, «Отмена» переименования ищет имя `disk2` в состоянии, где
    его уже нет, — выбор теряется."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            _SETTLE,
            _click(_AT_DISK),
            *_rename(0, "disk2"),
            _SETTLE,
            {"op": "drag", "from": _AT_DISK, "to": [10, 0]},
            _SETTLE,
            _snap("dragged", _FIELDS),
            _UNDO,
            _SETTLE,
            _snap("undo1", _FIELDS),
            _UNDO,
            _SETTLE,
            _snap("undo2", _FIELDS),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert s["dragged"]["fields"] == _offs("10", "60", "-70"), f"предусловие: диск перетащен: {s['dragged']!r}"
    assert s["undo1"]["fields"] == _OFF3 and s["undo1"]["selected"] == ["disk2"], (
        f"«Отмена» перетаскивания: {s['undo1']!r}"
    )
    assert _eff(s["undo2"]) == _INITIAL, f"«Отмена» переименования вернула имя: {_eff(s['undo2'])!r}"
    assert s["undo2"]["selected"] == ["disk"], f"выбор должен пережить обе «Отмены»: {s['undo2']['selected']!r}"


def test_h10_duplicate_name_delete_removes_the_selected_row(start_pult) -> None:
    """(h10) Выбран letter (строка 1); в форме ему дали имя `disk` (дубль имени строки 0); «Удалить» -> удалена
    строка 1 (бывший letter), остались настоящий disk и cap.

    Что ломает: «Удалить» ищет индекс по имени и берёт ПЕРВОЕ совпадение — строку 0 (настоящий disk) —
    остались бы letter и cap. Форма допускает дубли (правка полей не проверяет), бэкенд отклонит их лишь при
    сохранении."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            _SETTLE,
            _click(_AT_LETTER),
            *_rename(1, "disk"),
            _SETTLE,
            _btn("btnLayerDelete"),
            _SETTLE,
            _snap("deleted"),
        ],
    )
    _assert_ran(out)
    form = _eff(out["snaps"]["deleted"])
    assert [ly["name"] for ly in form] == ["disk", "cap"], f"после удаления должны остаться disk и cap: {form!r}"
    assert [ly["sprite_source"] for ly in form] == ["sprites/disk.png", "sprites/cap.png"], (
        f"удалён не тот слой (остался letter вместо disk?): {[ly['sprite_source'] for ly in form]!r}"
    )
    assert out["snaps"]["deleted"]["selected"] == [], f"после удаления выбирать нечего: {out['snaps']['deleted']!r}"


def test_h11_duplicate_name_arrow_moves_the_selected_row(start_pult) -> None:
    """(h11) Выбран letter (строка 1); ему дали имя `disk` (дубль строки 0); стрелка вправо -> сдвигается строка 1
    (60 -> 61), строка 0 остаётся на 0, подсвечена ровно одна строка.

    Что ломает: стрелка ищет слой по имени и берёт первое совпадение — сдвинула бы настоящий disk (0 -> 1)."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            _SETTLE,
            _click(_AT_LETTER),
            *_rename(1, "disk"),
            _SETTLE,
            _snap("renamed", _FIELDS),
            _KEY_RIGHT,
            _SETTLE,
            _snap("arrow", _FIELDS),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert s["renamed"]["fields"] == _OFF3, f"предусловие: само переименование ничего не двигает: {s['renamed']!r}"
    assert s["arrow"]["fields"] == _offs("0", "61", "-70"), (
        f"стрелка должна сдвинуть строку 1: {s['renamed']['fields']!r} -> {s['arrow']['fields']!r}"
    )
    assert len(s["arrow"]["selected"]) == 1, f"подсвечена ровно одна строка: {s['arrow']['selected']!r}"


_UP_PATH = "../../data/line_sim/up.png"
_PUT_OK = {"status": "ok", "file": {"path": "up.png", "sprite_source": _UP_PATH}}
_REFUSAL = {"status": "error", "code": "io_error", "message": "каталога нет"}
_CHOOSE = {"op": "choose_file", "id": "presetSpriteFile", "name": "up.png", "dataUrl": "data:image/png;base64,QUJD"}
_PUT = "/api/preset/sprite_put"


def test_h12_orphan_upload_when_list_refresh_fails_says_both(start_pult) -> None:
    """(h12) Пресет не загружен; загрузка PNG прошла (файл сохранён), а обновление списка спрайтов после неё отказало.
    Текст ошибки содержит ОБА факта: «файл up.png сохранён, слой не добавлен: пресет не загружен» И причину отказа
    списка («список спрайтов не получен: каталога нет»).

    Что ломает: обновление списка отказало -> старый код всё равно пишет только «сохранён, слой не добавлен» поверх
    текста отказа, и причина, по которой список пуст/устарел, теряется."""
    stand = _stand(start_pult, _INITIAL, sprites_replies=[_SPRITES_OK, _REFUSAL])
    stand.scene.responses["preset.get"] = {"status": "error", "code": "unavailable", "message": "нет"}
    out = _run_canvas(
        stand.port,
        [
            {"op": "stub_fetch", "path": _PUT, "status": 200, "json": _PUT_OK},
            {"op": "sleep", "ms": 500},
            _CHOOSE,
            {"op": "settle"},
            _snap("after"),
        ],
    )
    text = out["snaps"]["after"]["spritesError"]
    assert "файл up.png сохранён, слой не добавлен: пресет не загружен" in text, f"нет факта сохранения: {text!r}"
    assert "список спрайтов не получен: каталога нет" in text, f"причина отказа списка потеряна: {text!r}"


def test_h13_orphan_notice_cleared_when_preset_arrives(start_pult) -> None:
    """(h13) Загрузка PNG прошла ДО того, как пресет загрузился (`preset.get` двойника отвечает через 1.2 с): виден
    текст «файл ... сохранён, слой не добавлен: пресет не загружен». Когда пресет пришёл, текст исчезает — он
    описывал состояние, которого уже нет.

    Что ломает: текст-«сирота» остаётся на странице навсегда, хотя пресет загружен и слои редактируются."""
    stand = _stand(start_pult, _INITIAL)
    ok = dict(stand.scene.responses["preset.get"])

    def slow_get(args: dict) -> dict:
        time.sleep(1.2)
        return json.loads(json.dumps(ok))

    stand.scene.handlers["preset.get"] = slow_get
    out = _run_canvas(
        stand.port,
        [
            {"op": "stub_fetch", "path": _PUT, "status": 200, "json": _PUT_OK},
            {"op": "sleep", "ms": 100},
            _CHOOSE,
            {"op": "sleep", "ms": 400},
            _snap("uploaded"),
            {"op": "sleep", "ms": 1500},
            {"op": "settle"},
            _snap("preset_loaded"),
        ],
    )
    snaps = out["snaps"]
    assert "сохранён, слой не добавлен" in snaps["uploaded"]["spritesError"], (
        f"предусловие: текст-сирота показан: {snaps['uploaded']['spritesError']!r}"
    )
    assert snaps["preset_loaded"]["rev"] == "рев.: rev-1", f"предусловие: пресет пришёл: {snaps['preset_loaded']!r}"
    assert snaps["preset_loaded"]["spritesError"] == "", (
        f"текст остался после прихода пресета: {snaps['preset_loaded']['spritesError']!r}"
    )


_ANGLES = ["layer0_angle_deg", "layer1_angle_deg", "layer2_angle_deg"]  # порядок _INITIAL: disk 12.5, letter 0, cap 0
_LETTER_ROT_HANDLE = [60, -39]  # рамка letter на экране: x 45..75, y -15..15; ручка поворота — над центром на 24 px


def test_h14_renamed_selected_layer_keeps_canvas_handles(start_pult) -> None:
    """(h14) Выбран letter кликом по канве; в форме он переименован (change, ждём ответ раскладки с НОВЫМ именем);
    ручка поворота перетащена на 90 ПО часовой -> угол letter (строка 1) стал -90, углы disk (12.5) и cap (0)
    не изменились.

    Что ломает: слушатель `change` на #presetLayers перестаёт переносить выбор на новое имя (`presetSelected` остаётся
    «letter»). Действия идут по строке и этого не заметят, а рамка, ручки и разбор нажатия на канве ищут запись
    раскладки по ИМЕНИ: «letter» в раскладке уже нет, ручек нет, перетаскивание ничего не меняет."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            _SETTLE,
            _click(_AT_LETTER),
            *_rename(1, "letter2"),
            _SETTLE,  # ответ раскладки с новым именем принят
            _snap("renamed", _ANGLES),
            {"op": "drag", "from": _LETTER_ROT_HANDLE, "to": [60 + 39, 0], "steps": 4},
            _SETTLE,
            _snap("rotated", _ANGLES),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert stand.layout_requests()[-1]["preset"]["layers"][1]["name"] == "letter2", (
        "предусловие: раскладка с новым именем"
    )
    before, after = s["renamed"]["fields"], s["rotated"]["fields"]
    assert before == {"layer0_angle_deg": "12.5", "layer1_angle_deg": "0", "layer2_angle_deg": "0"}, before
    assert abs(float(after["layer1_angle_deg"]) - (-90)) < 0.2, f"ручка переименованного слоя не сработала: {after!r}"
    assert (after["layer0_angle_deg"], after["layer2_angle_deg"]) == ("12.5", "0"), f"сдвинут чужой слой: {after!r}"
