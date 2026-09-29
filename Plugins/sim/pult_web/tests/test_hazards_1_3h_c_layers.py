# -*- coding: utf-8 -*-
# ruff: noqa: F811 - фикстура start_pult импортирована из приёмки и принимается тестами по имени
"""Хазарды автора Task 1.3h-c — список слоёв (добавить / удалить / выше / ниже / заменить) на `pult_web`.

Дополняют слепую приёмку `test_acceptance_1_3h_c_layers.py` (её стенд, двойники и харнесс
переиспользуются импортом) там, где она по контракту молчит.

Что именно может сломаться в ЭТОМ механизме (так он устроен):
- операция над списком идёт мимо `presetApplyEdit` (свой брат `presetApplyLayersEdit`), а у
  стрелок есть отложенный запрос раскладки (`presetLayoutTimer`, 200 мс): если операция не
  снимает висящий таймер, он выстрелит ПОСЛЕ неё вторым запросом; если no-op снимает его
  раньше проверки «ничего не изменилось» — запрос стрелки потеряется, а битмап останется старым;
- ответ раскладки на СТАРЫЙ состав может прилететь после операции: без номера запроса
  (`presetLayoutSeq`) удалённый слой нарисуется обратно, а добавленный исчезнет с канвы;
- удаляемый слой могут в этот момент тащить: жест не должен пережить слой (иначе «Отмена»
  вернёт слой под живой жест, и отпускание указателя молча сдвинет его);
- имя нового слоя считается по ТЕКУЩЕЙ правке (поля формы), а не по `presetState`, и не по
  объекту-словарю (`constructor`, `__proto__` — не «занято»); `base`/`damaged` зарезервированы;
- «Отмена» удаления возвращает слой на его индекс, а выбор после неё — пуст (кнопки инертны).

Всё проверено только в харнессе `page_offline.mjs` (node:vm): фокус кнопок после клика
и события `<select>` настоящего браузера здесь не исполняются — это дело живого Chrome лида.
"""

from __future__ import annotations

import time
from typing import Callable

import pytest

from Plugins.sim.pult_web.tests.test_acceptance_1_3h_c_layers import (
    _A,
    _AT_CAP,
    _AT_DISK,
    _AT_LETTER,
    _B,
    _C,
    _CAP,
    _DISK,
    _DISK_SRC,
    _INITIAL,
    _LETTER,
    _READY,
    _SETTLE,
    _SPRITES_OK,
    _UNDO,
    _added,
    _assert_ran,
    _btn,
    _click,
    _data_url,
    _eff,
    _names,
    _pick,
    _run_canvas,
    _snap,
    _Stand,
    _stand,
    _state,
    start_pult,  # noqa: F401 - фикстура, pytest находит её по имени в модуле
)

_BASE_URL = _data_url("base")
_DISK_URL = _data_url("sprites/disk.png")
_LETTER_URL = _data_url("sprites/letter.png")
_CAP_URL = _data_url("sprites/cap.png")
_A_URL = _data_url("sprites/a.png")


def _delay_layout(stand: _Stand, when: Callable[[dict], bool], seconds: float) -> None:
    """Ответ `preset.layout` на тело, для которого `when(preset_layers)` истинно, задерживается."""
    original = stand.layers.handlers["preset.layout"]

    def slow(args: dict) -> dict:
        if when((args.get("preset") or {}).get("layers", [])):
            time.sleep(seconds)
        return original(args)

    stand.layers.handlers["preset.layout"] = slow


def _last_frame(out: dict, n: int) -> list[str]:
    """`src` последних `n` drawImage на основной канве = последний целиком нарисованный кадр (слои по порядку)."""
    return [d["src"] for d in out["draws"]][-n:]


def _arrow_moved_disk(layers: list[dict]) -> bool:
    return len(layers) >= 1 and layers[0].get("offset_px") == [1, 0]


def _is_delayed_body(layers: list[dict]) -> bool:
    """Тело запроса раскладки со СТАРЫМ составом (3 слоя, disk сдвинут стрелкой) — его ответ задерживается."""
    return len(layers) == 3 and _arrow_moved_disk(layers)


# --------------------------------------------------------------------------- #
# Таймер стрелок (presetLayoutTimer)                                          #
# --------------------------------------------------------------------------- #
def test_operation_cancels_pending_arrow_timer_single_request(start_pult) -> None:
    """Стрелка -> (таймер 200 мс висит) -> «Добавить» СРАЗУ: ровно ОДИН новый запрос раскладки — операции;
    таймер стрелки снят и второго запроса после паузы нет. Сдвиг стрелки (disk +1) в теле запроса есть:
    операция берёт снимок из полей, а не «старый» presetState. Положительный контроль — запрос был один И
    после паузы 700 мс (таймер сработал бы на 200-й мс)."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            {"op": "sleep", "ms": 300},
            _click(_AT_DISK),
            _snap("selected"),
            {"op": "key", "key": "ArrowRight"},
            _pick(_A),
            _btn("btnLayerAdd"),
            _snap("after_op"),
            {"op": "sleep", "ms": 700},
            _snap("settled"),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert s["selected"]["selected"] == ["disk"], "контроль: клик выбрал disk"
    assert s["after_op"]["layoutCount"] == s["selected"]["layoutCount"] + 1, (
        f"«Добавить» при висящем таймере стрелки: ровно один запрос раскладки: {s['selected']['layoutCount']} -> "
        f"{s['after_op']['layoutCount']}"
    )
    assert s["settled"]["layoutCount"] == s["after_op"]["layoutCount"], (
        f"таймер стрелки должен быть снят операцией — второй запрос после паузы лишний: "
        f"{s['after_op']['layoutCount']} -> {s['settled']['layoutCount']}"
    )
    last = stand.layout_requests()[-1]["preset"]["layers"]
    assert _names(last) == ["disk", "letter", "cap", "a"] and last[0]["offset_px"] == [1, 0], (
        f"запрос операции несёт и сдвиг стрелки, и новый слой: {last!r}"
    )
    assert _eff(s["settled"])[0]["offset_px"] == [1, 0], "сдвиг стрелки не потерян"


def test_noop_operation_does_not_swallow_pending_arrow_request(start_pult) -> None:
    """Стрелка на верхнем слое -> «Выше» (no-op: у края) при висящем таймере: запрос стрелки ВСЁ РАВНО уходит
    (no-op не трогает таймер). Иначе битмап остался бы старым, хотя presetState уже сдвинут."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            {"op": "sleep", "ms": 300},
            _click(_AT_CAP),
            _snap("selected"),
            {"op": "key", "key": "ArrowRight"},
            _btn("btnLayerUp"),
            _snap("after_noop"),
            {"op": "sleep", "ms": 700},
            _snap("settled"),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert s["selected"]["selected"] == ["cap"], "контроль: клик выбрал cap"
    assert s["after_noop"]["layoutCount"] == s["selected"]["layoutCount"], "no-op: своего запроса нет"
    assert s["settled"]["layoutCount"] == s["selected"]["layoutCount"] + 1, (
        f"запрос отложенной стрелки после no-op должен уйти: {s['selected']['layoutCount']} -> "
        f"{s['settled']['layoutCount']}"
    )
    assert stand.layout_requests()[-1]["preset"]["layers"][2]["offset_px"] == [-69, -70]


# --------------------------------------------------------------------------- #
# Запоздалый ответ раскладки (presetLayoutSeq)                                #
# --------------------------------------------------------------------------- #
def test_late_layout_reply_for_old_state_does_not_draw_deleted_layer_back(start_pult) -> None:
    """Стрелка (запрос уходит по таймеру, ответ на него задержан на 1 с) -> «Удалить» letter -> ответ на
    старый состав (с letter) прилетает ПОСЛЕ удаления. Последний нарисованный кадр — base, disk, cap: letter
    обратно не нарисован. Контроль — задержанный запрос действительно был (3 слоя, disk +1)."""
    stand = _stand(start_pult, _INITIAL)
    _delay_layout(stand, _is_delayed_body, 1.0)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            {"op": "sleep", "ms": 300},
            _click(_AT_DISK),
            {"op": "key", "key": "ArrowRight"},
            {"op": "sleep", "ms": 350},  # таймер (200 мс) отработал, запрос в полёте
            _click(_AT_LETTER),
            _btn("btnLayerDelete"),
            {"op": "sleep", "ms": 1800},  # задержанный ответ давно прилетел
            _snap("settled"),
        ],
    )
    _assert_ran(out)
    delayed = [r for r in stand.layout_requests() if _is_delayed_body(r["preset"]["layers"])]
    assert delayed, f"контроль: запрос со старым составом (3 слоя, стрелка) не уходил: {stand.layout_requests()!r}"
    assert _names(_state(out["snaps"]["settled"])) == ["disk", "cap"]
    assert _last_frame(out, 3) == [_BASE_URL, _DISK_URL, _CAP_URL], (
        "последний кадр канвы — base, disk, cap; удалённый letter вернулся бы из запоздалого ответа"
    )


def test_late_layout_reply_for_old_state_does_not_drop_added_layer(start_pult) -> None:
    """Зеркало: стрелка (ответ задержан 1 с) -> «Добавить» a.png -> запоздалый ответ на состав БЕЗ a не затирает
    канву: последний кадр — base, disk, letter, cap, a."""
    stand = _stand(start_pult, _INITIAL)
    _delay_layout(stand, _is_delayed_body, 1.0)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            {"op": "sleep", "ms": 300},
            _click(_AT_DISK),
            {"op": "key", "key": "ArrowRight"},
            {"op": "sleep", "ms": 350},
            _pick(_A),
            _btn("btnLayerAdd"),
            {"op": "sleep", "ms": 1800},
            _snap("settled"),
        ],
    )
    _assert_ran(out)
    delayed = [r for r in stand.layout_requests() if _is_delayed_body(r["preset"]["layers"])]
    assert delayed, f"контроль: запрос со старым составом не уходил: {stand.layout_requests()!r}"
    assert _names(_state(out["snaps"]["settled"])) == ["disk", "letter", "cap", "a"]
    assert _last_frame(out, 5) == [_BASE_URL, _DISK_URL, _LETTER_URL, _CAP_URL, _A_URL], (
        "последний кадр канвы обязан содержать добавленный слой a"
    )


# --------------------------------------------------------------------------- #
# Удаление при живом жесте                                                    #
# --------------------------------------------------------------------------- #
def test_delete_during_drag_cancels_gesture_no_ghost_move_after_undo(start_pult) -> None:
    """Тащат letter (нажатие + сдвиг, указатель не отпущен) -> «Удалить» -> «Отмена» (letter вернулся) ->
    указатель отпущен. Жест обязан быть оборван при удалении: отпускание не двигает вернувшийся слой и не
    оставляет записи «Отмена» (вторая «Отмена» ничего не меняет). Без обрыва живой жест (`name: letter`)
    сдвинул бы возвращённый слой на 20 px."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            {"op": "sleep", "ms": 300},
            {"op": "press", "at": _AT_LETTER},
            {"op": "move", "at": [_AT_LETTER[0] + 10, _AT_LETTER[1]]},
            {"op": "move", "at": [_AT_LETTER[0] + 20, _AT_LETTER[1]]},
            _btn("btnLayerDelete"),
            _SETTLE,
            _snap("deleted"),
            _UNDO,
            _SETTLE,
            _snap("undone"),
            {"op": "release", "at": [_AT_LETTER[0] + 20, _AT_LETTER[1]]},
            _SETTLE,
            _snap("released"),
            _UNDO,
            _SETTLE,
            _snap("undone2"),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert _state(s["deleted"]) == [_DISK, _CAP], f"контроль: слой удалён: {s['deleted']['layers']!r}"
    assert _state(s["undone"]) == _INITIAL, "«Отмена» удаления вернула letter на прежнее место"
    assert _state(s["released"]) == _INITIAL, (
        f"отпускание указателя после удаления не должно двигать вернувшийся слой: {s['released']['layers']!r}"
    )
    assert s["released"]["layoutCount"] == s["undone"]["layoutCount"], "жест оборван: запроса раскладки от него нет"
    assert _state(s["undone2"]) == _INITIAL, "оборванный жест не оставил записи «Отмена»"


# --------------------------------------------------------------------------- #
# Имена новых слоёв                                                           #
# --------------------------------------------------------------------------- #
def _files_reply(files: list[tuple[str, str]]) -> dict:
    return {**_SPRITES_OK, "files": [{"path": p, "sprite_source": src} for p, src in files]}


def test_reserved_and_special_names(start_pult) -> None:
    """`base.png` -> `base_2` (авто-слой base зарезервирован), повтор -> `base_3`; `damaged.PNG` -> `damaged_2`;
    `constructor.png` -> `constructor` (имя из прототипа объекта НЕ считается занятым); `v1.2.png` -> `v1.2`
    (срезается только последнее расширение). У каждого файла свой sprite_source (страница ищет запись по value)."""
    files = [
        ("base.png", _A),
        ("damaged.PNG", _C),
        ("constructor.png", _B),
        ("v1.2.png", _DISK_SRC),
    ]
    source = dict(files)
    stand = _stand(start_pult, _INITIAL, sprites_replies=[_files_reply(files)])
    steps: list[dict] = [_READY, {"op": "sleep", "ms": 300}]
    for path in ("base.png", "base.png", "damaged.PNG", "constructor.png", "v1.2.png"):
        steps += [_pick(source[path]), _btn("btnLayerAdd")]
    steps += [_SETTLE, _snap("after")]
    out = _run_canvas(stand.port, steps)
    _assert_ran(out)
    assert _names(_state(out["snaps"]["after"]))[3:] == ["base_2", "base_3", "damaged_2", "constructor", "v1.2"]


def test_name_uniqueness_uses_form_state_and_keeps_unsaved_edits(start_pult) -> None:
    """Слой letter переименован в форме в `a` (presetState ещё `letter`) и поле disk правлено (offset_x = 5) —
    без «Сохранить». «Добавить» a.png -> имя `a_2` (занятость считается по ПОЛЯМ формы), правки полей операция
    не теряет (снимок из collectPresetFromFields), «Отмена» возвращает состояние с правками полей."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            {"op": "sleep", "ms": 300},
            {"op": "set_field", "id": "layer1_name", "value": "a"},
            {"op": "set_field", "id": "layer0_offset_x", "value": 5},
            _pick(_A),
            _btn("btnLayerAdd"),
            _SETTLE,
            _snap("after"),
            _UNDO,
            _SETTLE,
            _snap("undone"),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    edited = [{**_DISK, "offset_px": [5, 0]}, {**_LETTER, "name": "a"}, _CAP]
    assert _state(s["after"]) == [*edited, _added("a_2", _A)], f"состав после «Добавить»: {s['after']['layers']!r}"
    assert _eff(s["undone"]) == edited, (
        f"«Отмена» возвращает правку полей, а не голый presetState: {s['undone']['form']!r}"
    )


# --------------------------------------------------------------------------- #
# «Отмена» удаления                                                           #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "at, index",
    [
        pytest.param(_AT_DISK, 0, id="first"),
        pytest.param(_AT_CAP, 2, id="last"),
    ],
)
def test_undo_delete_restores_index_and_leaves_no_selection(start_pult, at: list[float], index: int) -> None:
    """Удалён ПЕРВЫЙ / ПОСЛЕДНИЙ слой, «Отмена» -> слой на прежнем индексе (в C5 — средний). Выбор после
    «Отмены» пуст (после удаления его нет, «Отмена» его не воскрешает), и кнопки инертны: «Выше» ни запроса,
    ни записи — цепочка «Выше» на выбранном слое сразу после работает (контроль)."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            {"op": "sleep", "ms": 300},
            _click(at),
            _btn("btnLayerDelete"),
            _SETTLE,
            _snap("deleted"),
            _UNDO,
            _SETTLE,
            _snap("undone"),
            _btn("btnLayerUp"),
            _SETTLE,
            _snap("inert"),
            _click(at),
            _btn("btnLayerDown"),
            _SETTLE,
            _snap("control"),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert len(_state(s["deleted"])) == 2
    assert _state(s["undone"]) == _INITIAL, f"слой на прежнем индексе {index}: {s['undone']['layers']!r}"
    assert s["undone"]["selected"] == [], f"выбор после «Отмены» удаления пуст: {s['undone']['selected']!r}"
    assert s["inert"]["layoutCount"] == s["undone"]["layoutCount"], "«Выше» без выбора: запроса раскладки нет"
    assert _state(s["inert"]) == _INITIAL
    assert s["control"]["layoutCount"] == s["inert"]["layoutCount"] + (1 if index > 0 else 0), (
        f"контроль: «Ниже» на выбранном слое {'работает' if index > 0 else 'у нижнего — no-op'}"
    )


def test_replace_with_same_source_is_noop(start_pult) -> None:
    """«Заменить картинку» тем же файлом, что уже у слоя — ничего не изменилось: ни запроса, ни записи «Отмена».
    Контроль — другой файл ТОЙ ЖЕ кнопкой работает и это единственная запись в стеке."""
    stand = _stand(start_pult, _INITIAL)
    out = _run_canvas(
        stand.port,
        [
            _READY,
            {"op": "sleep", "ms": 300},
            _click(_AT_DISK),
            _snap("selected"),
            _pick(_DISK_SRC),
            _btn("btnLayerSprite"),
            _SETTLE,
            _snap("same"),
            _pick(_C),
            _btn("btnLayerSprite"),
            _SETTLE,
            _snap("other"),
            _UNDO,
            _SETTLE,
            _snap("u1"),
            _UNDO,
            _SETTLE,
            _snap("u2"),
        ],
    )
    _assert_ran(out)
    s = out["snaps"]
    assert s["same"]["layoutCount"] == s["selected"]["layoutCount"], "тот же файл: запроса раскладки нет"
    assert _state(s["same"]) == _INITIAL
    assert _state(s["other"])[0]["sprite_source"] == _C
    assert _state(s["u1"]) == _INITIAL and _state(s["u2"]) == _INITIAL, "запись в стеке одна: вторая «Отмена» пуста"
    assert s["u1"]["layoutCount"] == s["other"]["layoutCount"] + 1
    assert s["u2"]["layoutCount"] == s["u1"]["layoutCount"], "пустой стек: «Отмена» не запрашивает раскладку"
