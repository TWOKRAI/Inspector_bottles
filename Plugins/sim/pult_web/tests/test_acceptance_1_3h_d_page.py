# -*- coding: utf-8 -*-
"""RED-приёмка Task 1.3h-d (страница) — загрузка PNG из браузера на странице редактора слоёв `pult_web`.

Независимый tester вслепую, worktree `d-tester-page`, коммит `b2103448` (спецификация, реализации нет).
Источник — только раздел «Страница» и «Acceptance criteria» плана
`plans/line-sim-layer-editor/task-1.3h-d-upload.md`. Реализация страницы для этого нового кода не читалась
(страница читалась только как есть сейчас, до правки).

Контракт, который пинит этот файл (своими словами)
====================================================
1. Разметка `GET /`: ровно один `<input id="presetSpriteFile" type="file" accept="image/png">`.
2. На `change`: содержимое выбранного файла читается `FileReader.readAsDataURL`, префикс `data:...;base64,`
   отбрасывается, уходит `POST /api/preset/sprite_put` с телом РОВНО `{name: <file.name>, png_b64: <base64>}`.
3. Успех (`status == "ok"` и есть `file`): список спрайтов запрашивается ещё раз (`POST /api/preset/sprites`
   ПОСЛЕ загрузки; новый файл появляется в `<select>`) и добавляется слой с `sprite_source` = `r.file.sprite_source`
   (тот же путь, что «Добавить» из списка: один слой в конец, один запрос раскладки).
4. Отказ (любой ответ не-успех, в т.ч. `ok` без `file`): текст `message || error || code` виден в
   `#presetSpritesError`, слой НЕ добавляется.
5. После обработки — успех или отказ: `input.value === ""` (тот же файл можно выбрать снова) и фокус —
   канве `#presetCanvas`, вызовом `focus({ preventScroll: true })` (урок F1 1.3h-c).

Как это измеряется (что харнесс видит, а что нет)
---------------------------------------------------
Харнесс `page_offline.mjs` расширен ТОЛЬКО аддитивно (тест-инфраструктура): заглушка `FileReader`, модель
`<input type=file>` (`files`, `value`; запись `""` очищает `files`, запись непустой строки — исключение, как в
браузере), шаги `stub_fetch` (ответ на путь подменён — маршрут `sprite_put` тут НЕ участвует, им занят другой
тест), `choose_file`, `settle` (ждать, пока цепочка чтение -> POST -> список не затихнет). Список спрайтов
(`/api/preset/sprites`) идёт через настоящий плагин и двойник `layers`.
Харнесс слеп к умолчаниям браузера (куда реально уходит фокус после закрытия диалога выбора файла, что делает
Space на сфокусированном контроле) — этот файл проверяет только `document.activeElement` и опции `focus()`
после обработчика; остальное — живой Chrome у лида.
Слушатель `FileReader` — `onload` или `addEventListener("load")`: заглушка поддерживает оба, тест механизм не пинит.
"""

# ruff: noqa: F811  (start_pult — фикстура из соседнего файла: ре-импорт и параметр теста)

from __future__ import annotations

import json
import urllib.request
from html.parser import HTMLParser

import pytest

from Plugins.sim.pult_web.tests.test_acceptance_1_3h_c_layers import (  # noqa: F401  (start_pult — фикстура)
    _FILES,
    _INITIAL,
    _READY,
    _SETTLE,
    _SPRITES,
    _SPRITES_OK,
    _assert_ran,
    _run_canvas,
    _snap,
    _stand,
    start_pult,
)


_INPUT = "presetSpriteFile"
_PUT = "/api/preset/sprite_put"
_SPRITES_PATH = "/api/preset/sprites"
_UP_SRC = "../../data/line_sim/up.png"
_OK_REPLY = {"status": "ok", "file": {"path": "up.png", "sprite_source": _UP_SRC}}
_UP_DATA_URL = "data:image/png;base64,QUJD"  # base64("ABC")
_SPRITES_WITH_UP = {**_SPRITES_OK, "files": [*_FILES, {"path": "up.png", "sprite_source": _UP_SRC}]}
_ERR_CONFLICT = {"status": "error", "code": "conflict", "message": "уже есть"}


@pytest.fixture(autouse=True)
def _layout_knows_uploaded_sprite(monkeypatch: pytest.MonkeyPatch) -> None:
    """Двойник раскладки отвечает `invalid` на неизвестный спрайт — загруженный файл ему известен."""
    monkeypatch.setitem(_SPRITES, _UP_SRC, _SPRITES["sprites/a.png"])


# --------------------------------------------------------------------------- #
# Шаги сценария                                                               #
# --------------------------------------------------------------------------- #
def _stub_put(reply: dict, status: int = 200) -> dict:
    return {"op": "stub_fetch", "path": _PUT, "status": status, "json": reply}


def _choose(name: str = "up.png", data_url: str = _UP_DATA_URL) -> dict:
    return {"op": "choose_file", "id": _INPUT, "name": name, "dataUrl": data_url}


_SETTLED = {"op": "settle"}
_FOCUS_INPUT = {"op": "focus_el", "id": _INPUT}


def _upload(
    stand_port: int,
    reply: dict,
    *,
    status: int = 200,
    name: str = "up.png",
    data_url: str = _UP_DATA_URL,
    extra: list[dict] | None = None,
) -> dict:
    """Сценарий: канва готова, фокус на контроле (как после клика по нему), снимок `before`, файл выбран,
    цепочка затихла, снимок `after`; `extra` — шаги после `after` (с их снимками)."""
    out = _run_canvas(
        stand_port,
        [
            _stub_put(reply, status),
            _READY,
            _SETTLE,
            _FOCUS_INPUT,
            _snap("before", [_INPUT]),
            _choose(name, data_url),
            _SETTLED,
            _snap("after", [_INPUT]),
            *(extra or []),
        ],
    )
    _assert_ran(out)
    return out


def _put_posts(out: dict) -> list[dict]:
    return [e for e in out["fetchLog"] if e["path"] == _PUT]


def _sprite_posts(out: dict) -> list[int]:
    """Индексы запросов списка спрайтов в журнале fetch (порядок вызовов страницы)."""
    return [i for i, e in enumerate(out["fetchLog"]) if e["path"] == _SPRITES_PATH and e["method"] == "POST"]


# --------------------------------------------------------------------------- #
# 1 — разметка                                                                #
# --------------------------------------------------------------------------- #
class _Attrs(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.found: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        d = dict(attrs)
        if d.get("id") == _INPUT:
            self.found.append((tag, d))


def test_d1_markup_has_png_file_input(start_pult) -> None:
    """Контроль загрузки есть: ровно один `<input id=presetSpriteFile type=file accept=image/png>` в `GET /`."""
    port = start_pult()
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as resp:
        html = resp.read().decode("utf-8")
    parser = _Attrs()
    parser.feed(html)
    assert len(parser.found) == 1, f"в разметке `GET /` ровно один id={_INPUT!r}: {parser.found!r}"
    tag, attrs = parser.found[0]
    assert tag == "input", f"контроль — <input>, а не {tag!r}"
    assert attrs.get("type") == "file", f"type=file: {attrs!r}"
    assert attrs.get("accept") == "image/png", f"accept=image/png: {attrs!r}"


# --------------------------------------------------------------------------- #
# 2 — что уходит в POST                                                       #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("name", "data_url", "png_b64"),
    [
        ("up.png", "data:image/png;base64,QUJD", "QUJD"),
        # кириллица + пробел в имени; base64 с `+`, `/` и `=` в конце — ничего не обрезано и не перекодировано
        ("снимок 1.png", "data:image/png;base64,iVBORw0KGgo+/A==", "iVBORw0KGgo+/A=="),
    ],
)
def test_d2_success_posts_name_and_bare_base64(start_pult, name: str, data_url: str, png_b64: str) -> None:
    """Выбор файла -> ровно один `POST /api/preset/sprite_put`, тело ровно `{name, png_b64}` без префикса data:."""
    stand = _stand(start_pult, _INITIAL, sprites_replies=[_SPRITES_OK, _SPRITES_WITH_UP])
    out = _upload(stand.port, _OK_REPLY, name=name, data_url=data_url)
    posts = _put_posts(out)
    assert len(posts) == 1, f"ровно один запрос на выбор файла: {posts!r}"
    assert posts[0]["method"] == "POST", posts[0]
    assert json.loads(posts[0]["body"]) == {"name": name, "png_b64": png_b64}, f"тело запроса: {posts[0]['body']!r}"


# --------------------------------------------------------------------------- #
# 3 — успех: слой и обновлённый список                                        #
# --------------------------------------------------------------------------- #
def test_d3_success_adds_one_layer_with_returned_sprite_source(start_pult) -> None:
    """Успех -> к пресету добавлен ровно ОДИН слой (в конец) с `sprite_source` из ответа, прежние слои те же,
    один запрос раскладки; текст отказа списка пуст."""
    stand = _stand(start_pult, _INITIAL, sprites_replies=[_SPRITES_OK, _SPRITES_WITH_UP])
    out = _upload(stand.port, _OK_REPLY)
    before, after = out["snaps"]["before"], out["snaps"]["after"]
    assert before["layers"] == _INITIAL, f"контроль: до загрузки три слоя: {before['layers']!r}"
    layers = after["layers"]
    assert layers is not None and len(layers) == len(_INITIAL) + 1, f"ровно один новый слой: {layers!r}"
    assert layers[: len(_INITIAL)] == _INITIAL, f"прежние слои не тронуты: {layers!r}"
    assert layers[-1]["sprite_source"] == _UP_SRC, f"sprite_source из ответа: {layers[-1]!r}"
    assert after["layoutCount"] - before["layoutCount"] == 1, (
        f"как «Добавить»: один запрос раскладки: {before['layoutCount']} -> {after['layoutCount']}"
    )
    assert after["spritesError"].strip() == "", f"успех без текста отказа: {after['spritesError']!r}"


def test_d3_success_rerequests_sprites_and_new_file_is_in_the_select(start_pult) -> None:
    """Успех -> `POST /api/preset/sprites` запрошен ЕЩЁ РАЗ после `sprite_put` и загруженный файл — пункт `<select>`."""
    stand = _stand(start_pult, _INITIAL, sprites_replies=[_SPRITES_OK, _SPRITES_WITH_UP])
    out = _upload(stand.port, _OK_REPLY)
    log = out["fetchLog"]
    put_at = [i for i, e in enumerate(log) if e["path"] == _PUT]
    assert len(put_at) == 1, f"контроль: одна загрузка: {put_at!r}"
    assert any(i > put_at[0] for i in _sprite_posts(out)), (
        f"список спрайтов не запрошен после загрузки: {[(e['method'], e['path']) for e in log]!r}"
    )
    values = [o["value"] for o in out["snaps"]["after"]["sel"]["options"]]
    assert _UP_SRC in values, f"новый файл — пункт списка: {values!r}"


# --------------------------------------------------------------------------- #
# 4 — отказ: текст виден, слой не добавлен                                    #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("reply", "http", "shown"),
    [
        (_ERR_CONFLICT, 409, "уже есть"),  # message
        ({"status": "error", "error": "диск полон"}, 500, "диск полон"),  # нет message -> error
        ({"status": "error", "code": "conflict"}, 409, "conflict"),  # нет message и error -> code
    ],
    ids=["message", "error", "code"],
)
def test_d4_refusal_shows_text_and_adds_no_layer(start_pult, reply: dict, http: int, shown: str) -> None:
    """Отказ -> `message || error || code` в #presetSpritesError, слоёв не прибавилось, раскладку не просили."""
    stand = _stand(start_pult, _INITIAL, sprites_replies=[_SPRITES_OK])
    out = _upload(stand.port, reply, status=http)
    before, after = out["snaps"]["before"], out["snaps"]["after"]
    assert before["spritesError"].strip() == "", f"контроль: до отказа текста нет: {before['spritesError']!r}"
    assert len(_put_posts(out)) == 1, "контроль: загрузка была предпринята"
    assert shown in after["spritesError"], f"текст отказа {shown!r} не показан: {after['spritesError']!r}"
    assert after["layers"] == _INITIAL, f"слой не добавляется при отказе: {after['layers']!r}"
    assert after["layoutCount"] == before["layoutCount"], "при отказе раскладку не пересчитывали"


def test_d4_ok_without_file_adds_no_layer_but_a_real_success_still_works(start_pult) -> None:
    """`status: ok` без `file` — не успех (нечего добавлять): слоя нет. Положительный контроль в том же тесте:
    следующая загрузка с нормальным ответом слой добавляет (иначе «слоя нет» зелёно и без страницы)."""
    stand = _stand(start_pult, _INITIAL, sprites_replies=[_SPRITES_OK, _SPRITES_WITH_UP])
    out = _upload(
        stand.port,
        {"status": "ok"},
        extra=[_stub_put(_OK_REPLY), _choose(), _SETTLED, _snap("second", [_INPUT])],
    )
    assert out["snaps"]["after"]["layers"] == _INITIAL, (
        f"ok без file: слой не добавляется: {out['snaps']['after']['layers']!r}"
    )
    second = out["snaps"]["second"]["layers"]
    assert second is not None and len(second) == len(_INITIAL) + 1 and second[-1]["sprite_source"] == _UP_SRC, (
        f"контроль: нормальный успех добавляет слой: {second!r}"
    )


# --------------------------------------------------------------------------- #
# 5 — после обработки: value сброшен, фокус на канве                          #
# --------------------------------------------------------------------------- #
_OUTCOMES = [pytest.param(_OK_REPLY, 200, id="success"), pytest.param(_ERR_CONFLICT, 409, id="refusal")]


@pytest.mark.parametrize(("reply", "http"), _OUTCOMES)
def test_d5_input_value_is_reset_after_success_and_after_refusal(start_pult, reply: dict, http: int) -> None:
    """И после успеха, и после отказа `input.value === ""` (тот же файл можно выбрать снова). Контроль: сразу
    после выбора харнесс ставит `C:\\fakepath\\up.png` — без сброса страницей значение осталось бы таким."""
    stand = _stand(start_pult, _INITIAL, sprites_replies=[_SPRITES_OK, _SPRITES_WITH_UP])
    out = _upload(stand.port, reply, status=http)
    assert len(_put_posts(out)) == 1, "контроль: загрузка была предпринята"
    assert out["snaps"]["before"]["fields"][_INPUT] == "", "контроль: до выбора значения нет"
    assert out["snaps"]["after"]["fields"][_INPUT] == "", (
        f"value контроля не сброшен: {out['snaps']['after']['fields'][_INPUT]!r}"
    )


@pytest.mark.parametrize(("reply", "http"), _OUTCOMES)
def test_d5_focus_goes_to_canvas_with_prevent_scroll(start_pult, reply: dict, http: int) -> None:
    """И после успеха, и после отказа фокус на `#presetCanvas` (не на контроле — иначе Space/Enter откроют диалог
    заново), все новые вызовы `focus()` канвы — с `{ preventScroll: true }` (страница не прыгает)."""
    stand = _stand(start_pult, _INITIAL, sprites_replies=[_SPRITES_OK, _SPRITES_WITH_UP])
    out = _upload(stand.port, reply, status=http)
    before, after = out["snaps"]["before"], out["snaps"]["after"]
    assert before["active"] == _INPUT, f"контроль: до выбора фокус на контроле: {before['active']!r}"
    assert len(_put_posts(out)) == 1, "контроль: загрузка была предпринята"
    assert after["active"] == "presetCanvas", f"фокус после обработки: {after['active']!r}"
    new_calls = after["focusCalls"][len(before["focusCalls"]) :]
    assert new_calls and all(c == {"preventScroll": True} for c in new_calls), (
        f"focus() канвы с preventScroll: {new_calls!r}"
    )
