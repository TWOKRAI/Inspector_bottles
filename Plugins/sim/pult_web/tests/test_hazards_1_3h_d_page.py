# -*- coding: utf-8 -*-
"""Hazard лида к загрузке PNG на странице (Task 1.3h-d) — дыра, найденная инъекцией I14.

Мутант «успех = `status: ok`, без проверки `file`» проходил все 13 приёмочных тестов: `presetAddLayer(undefined)`
бросает `TypeError`, `catch` показывает его текст — слоя нет, как и требует контракт, но случайно, через
исключение, и страница при этом уже перезапросила список спрайтов (ветка успеха). Здесь закреплено то, что
отличает отказ от успеха снаружи: ответ `ok` без `file` обрабатывается КАК отказ — список не перезапрашивается
(ровно столько запросов списка, сколько при обычном `conflict`), текст отказа показан.
"""

from __future__ import annotations

# ruff: noqa: F811  (start_pult — фикстура из соседнего файла: ре-импорт и параметр теста)


from Plugins.sim.pult_web.tests.test_acceptance_1_3h_c_layers import (  # noqa: F401  (start_pult — фикстура)
    _INITIAL,
    _SPRITES_OK,
    _stand,
    start_pult,
)
from Plugins.sim.pult_web.tests.test_acceptance_1_3h_d_page import (
    _ERR_CONFLICT,
    _FOCUS_INPUT,
    _INPUT,
    _OK_REPLY,
    _READY,
    _SETTLE,
    _SETTLED,
    _assert_ran,
    _choose,
    _put_posts,
    _run_canvas,
    _snap,
    _sprite_posts,
    _stub_put,
    _upload,
)


def _sprite_requests_after_upload(start_pult, reply: dict, status: int) -> tuple[int, dict]:
    stand = _stand(start_pult, _INITIAL, sprites_replies=[_SPRITES_OK, _SPRITES_OK])
    out = _upload(stand.port, reply, status=status)
    assert len(_put_posts(out)) == 1, "контроль: загрузка была предпринята"
    return len(_sprite_posts(out)), out["snaps"]["after"]


def test_ok_without_file_is_handled_as_a_refusal_not_as_a_success(start_pult) -> None:
    refusal_count, _ = _sprite_requests_after_upload(start_pult, _ERR_CONFLICT, 409)
    success_count, _ = _sprite_requests_after_upload(start_pult, _OK_REPLY, 200)
    assert success_count == refusal_count + 1, (
        f"контроль: успех перезапрашивает список, отказ — нет ({success_count} против {refusal_count})"
    )
    count, after = _sprite_requests_after_upload(start_pult, {"status": "ok"}, 200)
    assert count == refusal_count, f"ok без file перезапросил список, как успех: {count} против {refusal_count}"
    assert after["layers"] == _INITIAL, f"ok без file: слой не добавляется: {after['layers']!r}"
    assert after["spritesError"].strip(), "ok без file: текст отказа показан"


def test_file_over_6_mib_is_refused_before_reading_and_without_a_post(start_pult) -> None:
    """Файл 6 МиБ + 1 байт: страница отказывает по `file.size` — ни чтения (FileReader), ни POST `sprite_put`."""
    stand = _stand(start_pult, _INITIAL, sprites_replies=[_SPRITES_OK])
    out = _run_canvas(
        stand.port,
        [
            _stub_put(_OK_REPLY, 200),
            _READY,
            _SETTLE,
            _FOCUS_INPUT,
            {**_choose("big.png"), "size": 6_291_457},
            _SETTLED,
            _snap("after", [_INPUT]),
        ],
    )
    _assert_ran(out)
    after = out["snaps"]["after"]
    assert _put_posts(out) == [], "больше 6 МиБ: POST sprite_put не уходит"
    assert "6 МиБ" in after["spritesError"], f"текст отказа показан: {after['spritesError']!r}"
    assert after["fields"][_INPUT] == "", "контроль вводa сброшен (тот же файл можно выбрать снова)"
    assert after["layers"] == _INITIAL, "слой не добавлен"
