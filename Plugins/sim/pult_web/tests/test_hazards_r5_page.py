# -*- coding: utf-8 -*-
"""Hazard-тесты автора R-5 (а) — выбор слоя принадлежит СТРОКЕ формы.

Автор пишет их про внутренние места механизма, которые слепой tester (`test_acceptance_r5_page.py`) не видел:
выбор хранится парой «имя + строка», строка захватывается в «Отмене» ДО извлечения из стека, а решение «что считать
идентичностью слоя — строку или имя» зависит от того, была ли форма правлена (`presetDirty`) до нажатия. Ломаются
эти места тихо: подсветка/стрелка уходят на ЧУЖОЙ слой, ошибок в консоли нет.

Идиома та же, что в приёмке: харнесс `page_offline.mjs`, только наблюдаемое (поля формы, подсветка, тела запросов).
Никакого `pytest.mark.timeout` (плагин не установлен) — каждый блокирующий вызов харнесса ограничен его дедлайнами.
"""

# ruff: noqa: F811  (start_pult — фикстура из соседнего файла: ре-импорт и параметр теста)

from __future__ import annotations

import json

from Plugins.sim.pult_web.tests.test_acceptance_1_3h_c_layers import (  # noqa: F401  (start_pult — фикстура)
    _A,
    _AT_DISK,
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


def test_h2_delete_selected_then_undo_leaves_nothing_selected(start_pult) -> None:
    """(h2) Удалить выбранный disk, «Отмена» -> слой вернулся, но выбора НЕТ (подсвеченных строк нет), стрелка —
    no-op (ни одно смещение не меняется).

    Что ломает: «Отмена» после операции над составом (форма синхронна, `presetDirty=false`) выбирает по строке
    `presetSelectedRow`, оставшейся от до-удаления (0) — вернувшийся disk оказался бы выбранным «по воскрешению»;
    либо не сбрасывает `presetSelectedRow` при удалении, и подсветка/стрелка живут на пустом месте."""
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
    assert s["undone"]["selected"] == [], f"выбор не воскресает: {s['undone']['selected']!r}"
    assert (
        s["arrow"]["fields"]
        == s["undone"]["fields"]
        == {
            "layer0_offset_x": "0",
            "layer1_offset_x": "60",
            "layer2_offset_x": "-70",
        }
    ), f"стрелка без выбора не двигает ничего: {s['undone']['fields']!r} -> {s['arrow']['fields']!r}"


def test_h3_rename_then_add_then_undo_twice_selects_nothing_and_moves_nothing(start_pult) -> None:
    """(h3) Выбран disk; переименован в disk2 (выбор идёт за именем); «Добавить» a.png (операция над составом при
    ПРАВЛЕННОЙ форме -> выбран новый слой `a`); «Отмена» дважды -> слои как были (disk, letter, cap), выбора НЕТ,
    стрелка — no-op.

    Отличие от брифа лида: там ожидалось «выбор на исходной строке под исходным именем». По дизайну этого не будет:
    после «Добавить» выбран `a`, первая «Отмена» его убирает (F2, страж а4), вторая ничего не выбирает — выбор
    молча не воскресает. Ловим здесь именно чужой/призрачный выбор.

    Что ломает: «Отмена» №1 берёт строку 0 из `presetSelectedRow` (форма была правлена ДО «Добавить», но
    `presetDirty` после операции над составом уже false — ветка «по строке» не должна срабатывать); либо
    `presetSelected` остаётся на `disk2`/`a`, и после второй «Отмены» подсветка попадает на слой, получивший это
    имя случайно."""
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
    assert s["undo1"]["selected"] == [], f"добавленного слоя нет, выбирать нечего: {s['undo1']['selected']!r}"
    assert _eff(s["undo2"]) == _INITIAL, f"вторая «Отмена» вернула исходные слои: {_eff(s['undo2'])!r}"
    assert s["undo2"]["selected"] == [], f"ничего не выбрано: {s['undo2']['selected']!r}"
    assert (
        s["arrow"]["fields"]
        == s["undo2"]["fields"]
        == {
            "layer0_offset_x": "0",
            "layer1_offset_x": "60",
            "layer2_offset_x": "-70",
        }
    ), f"стрелка без выбора не двигает ничего: {s['undo2']['fields']!r} -> {s['arrow']['fields']!r}"


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
