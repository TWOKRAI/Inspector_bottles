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

import pytest

from Plugins.sim.pult_web.tests.test_acceptance_1_3h_c_layers import (  # noqa: F401  (start_pult — фикстура)
    _INITIAL,
    _SPRITES_OK,
    _stand,
    start_pult,
)
from Plugins.sim.pult_web.tests.test_acceptance_1_3h_d_page import (
    _ERR_CONFLICT,
    _OK_REPLY,
    _put_posts,
    _sprite_posts,
    _upload,
)

pytestmark = pytest.mark.timeout(60)


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
