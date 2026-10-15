# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты Task 1.2 (критерии 1-4): ключ ``overlay`` в item `code_reader_sdk`.

Написаны ДО реализации по `plans/code-reader-gui/phase-1.md`, Task 1.2. Реализацию
``_build_item`` автор не читал. Item получаем так же, как боевой путь: настоящий
``CodeReaderSdkPlugin`` на ``FakeApi`` -> ``take_device`` -> ``produce()``.

ПРЕДПОЛОЖЕНО (формат оверлея спека не фиксирует, взят из README `overlay_draw`):
  * ``overlay["lines"]`` — список ``{"p1": [x, y], "p2": [x, y], "group": "code_ok" | "code_bad"}`` (цвета нет);
  * ``overlay["points"]`` — список ``{"xy": [x, y], "label": str, ...}``;
  * строка статуса — точка ``xy == [10, 70]``, её ``label`` содержит
    ``ok N / no N / bad N`` (формат из DESIGN: ``"<status> · ok N / no N / bad N"``).
Одно место правки — хелперы ``_lines`` / ``_point_at`` / ``_status_counts`` ниже.
"""

from __future__ import annotations

import json
import re

from Services.code_reader.tests import test_sdk_plugin as _base
from Services.code_reader.tests.test_sdk_plugin import _cmd, _collect, _raw, _status, _walk
from Services.code_reader.tests.test_sdk_reader import FakeApi, bad_code as _bad_code, code as _code

# Фикстура плагина на FakeApi из соседнего модуля (pytest берёт её по имени из этого модуля).
make_plugin = _base.make_plugin

SQUARE = [[100, 100], [300, 100], [300, 300], [100, 300]]
OK_GROUP = "code_ok"  # цвет по группе задаёт color_table overlay_draw (решение владельца 2026-10-15)
BAD_GROUP = "code_bad"

_COUNTS_RE = re.compile(r"ok\s+(\d+)\s*/\s*no\s+(\d+)\s*/\s*bad\s+(\d+)")


# --------------------------------------------------------------------------
# Хелперы разбора overlay (единственное место, знающее форму)
# --------------------------------------------------------------------------


def _overlay(item: dict) -> dict:
    assert "overlay" in item, f"в item нет ключа overlay; ключи: {sorted(item)}"
    ov = item["overlay"]
    assert isinstance(ov, dict)
    return ov


def _lines(item: dict) -> list[tuple[tuple[int, int], tuple[int, int], str]]:
    return [(tuple(ln["p1"]), tuple(ln["p2"]), str(ln["group"])) for ln in _overlay(item).get("lines", [])]


def _points(item: dict) -> list[dict]:
    return list(_overlay(item).get("points", []))


def _point_at(item: dict, xy: list[int]) -> list[dict]:
    return [p for p in _points(item) if list(p["xy"]) == xy]


def _status_labels(item: dict) -> list[str]:
    return [str(p.get("label", "")) for p in _point_at(item, [10, 70])]


def _status_counts(item: dict) -> tuple[int, int, int]:
    labels = _status_labels(item)
    assert len(labels) == 1, f"ожидалась ровно одна строка статуса в (10, 70), есть: {labels}"
    m = _COUNTS_RE.search(labels[0])
    assert m, f"в строке статуса {labels[0]!r} нет 'ok N / no N / bad N'"
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _one_item(make_plugin, codes, trig: int = 1, **raw_kw) -> dict:
    w = make_plugin(FakeApi(script=[_raw(codes, trig, **raw_kw)]), timeout_ms=20)
    assert _cmd(w, "take_device")["status"] == "ok"
    (item,) = _collect(w, 1)
    return item


# --------------------------------------------------------------------------
# Критерий 1: ok — рамка из 4 отрезков и подпись с текстом
# --------------------------------------------------------------------------


def test_ok_code_has_exactly_four_closed_green_segments(make_plugin):
    item = _one_item(make_plugin, [_code("QR-15MM", corners=SQUARE)])

    assert _lines(item) == [
        ((100, 100), (300, 100), OK_GROUP),
        ((300, 100), (300, 300), OK_GROUP),
        ((300, 300), (100, 300), OK_GROUP),
        ((100, 300), (100, 100), OK_GROUP),
    ]


def test_ok_code_label_with_code_text_at_first_corner(make_plugin):
    item = _one_item(make_plugin, [_code("QR-15MM", corners=SQUARE)])

    labels = [(p.get("label"), p.get("group")) for p in _point_at(item, [100, 100])]
    assert labels == [("QR-15MM", "code_text_ok")]


# --------------------------------------------------------------------------
# Критерий 2: bad_code красный с подписью "bad_code"; no_code без линий
# --------------------------------------------------------------------------


def test_bad_code_segments_are_red_and_labelled_bad_code(make_plugin):
    item = _one_item(make_plugin, [_bad_code(corners=SQUARE)], no_read=1)

    assert item["status"] == "bad_code"  # предусловие: сценарий действительно bad_code
    assert _lines(item) == [
        ((100, 100), (300, 100), BAD_GROUP),
        ((300, 100), (300, 300), BAD_GROUP),
        ((300, 300), (100, 300), BAD_GROUP),
        ((100, 300), (100, 100), BAD_GROUP),
    ]
    assert [(p.get("label"), p.get("group")) for p in _point_at(item, [100, 100])] == [("bad_code", "code_text_bad")]


def test_no_code_has_no_lines_but_has_status_line(make_plugin):
    item = _one_item(make_plugin, [])

    assert item["status"] == "no_code"  # предусловие
    assert _overlay(item).get("lines", []) == []
    assert len(_status_labels(item)) == 1
    assert _status_labels(item)[0].startswith("no_code"), _status_labels(item)
    # подписей кодов нет: единственная точка — строка статуса
    assert [list(p["xy"]) for p in _points(item)] == [[10, 70]]


def test_status_line_present_for_ok_item_too(make_plugin):
    item = _one_item(make_plugin, [_code("QR-15MM", corners=SQUARE)])

    labels = _status_labels(item)
    assert len(labels) == 1
    assert labels[0].startswith("ok"), labels


# --------------------------------------------------------------------------
# Критерий 3: три числа строки статуса == счётчики дерева; после reset_stats нули
# --------------------------------------------------------------------------


def test_status_line_numbers_equal_tree_counters(make_plugin):
    script = [
        _raw([_code("QR-A", corners=SQUARE)], 1),
        _raw([_code("QR-B", corners=SQUARE)], 2),
        _raw([_code("QR-C", corners=SQUARE)], 3),
        _raw([], 4),
        _raw([], 5),
        _raw([_bad_code(corners=SQUARE)], 6, no_read=1),
    ]
    w = make_plugin(FakeApi(script=script), timeout_ms=20)
    _cmd(w, "take_device")
    items = _collect(w, 6)
    assert [i["trigger_index"] for i in items] == [1, 2, 3, 4, 5, 6]

    tree = _status(w)
    # предусловие: счётчики различимы между собой (иначе перепутанные местами числа не поймать)
    assert (tree["no_reads"], tree["bad_reads"]) == (2, 1)
    assert tree["total_reads"] not in (tree["no_reads"], tree["bad_reads"])

    assert _status_counts(items[-1]) == (tree["total_reads"], tree["no_reads"], tree["bad_reads"])


def test_status_line_numbers_follow_each_item(make_plugin):
    """Счётчик в оверлее растёт вместе с деревом: no-число 1-го и 5-го item разные."""
    script = [_raw([_code("QR-A", corners=SQUARE)], 1), _raw([], 2), _raw([], 3)]
    w = make_plugin(FakeApi(script=script), timeout_ms=20)
    _cmd(w, "take_device")
    items = _collect(w, 3)

    no_by_item = [_status_counts(i)[1] for i in items]
    assert no_by_item[0] == 0
    assert no_by_item[-1] == 2
    assert no_by_item == sorted(no_by_item)


def test_status_line_zero_after_reset_stats(make_plugin):
    api = FakeApi(
        script=[
            _raw([], 1),
            _raw([], 2),
            _raw([_bad_code(corners=SQUARE)], 3, no_read=1),
        ]
    )
    w = make_plugin(api, timeout_ms=20)
    _cmd(w, "take_device")
    before = _collect(w, 3)
    assert _status_counts(before[-1])[1:] == (2, 1)  # предусловие: счётчики были ненулевые

    _cmd(w, "reset_stats")
    tree = _status(w)
    assert (tree["total_reads"], tree["no_reads"], tree["bad_reads"]) == (0, 0, 0)

    api.script.append(_raw([_code("QR-A", corners=SQUARE)], 4))  # новый ok-кадр после сброса
    (after,) = _collect(w, 1)
    assert after["trigger_index"] == 4

    total, no, bad = _status_counts(after)
    assert (no, bad) == (0, 0)
    assert total <= 1  # сам этот кадр максимум один; не 3 из прошлой серии
    tree = _status(w)
    assert (total, no, bad) == (tree["total_reads"], tree["no_reads"], tree["bad_reads"])


# --------------------------------------------------------------------------
# Критерий 4: JSON, без bytes, размер item без кадра
# --------------------------------------------------------------------------


def _three_codes_item(make_plugin) -> dict:
    other = [[400, 100], [500, 100], [500, 200], [400, 200]]
    third = [[600, 100], [700, 100], [700, 200], [600, 200]]
    codes = [
        _code("QR-15MM", corners=SQUARE),
        _code("QR-20MM", corners=other),
        _code("QR-25MM", corners=third),
    ]
    return _one_item(make_plugin, codes)


def test_overlay_passes_json_dumps(make_plugin):
    item = _three_codes_item(make_plugin)

    ov = _overlay(item)
    assert len(ov["lines"]) == 12  # 3 кода x 4 отрезка: предусловие осмысленности
    dumped = json.dumps(ov)
    assert json.loads(dumped) == ov  # туда-обратно без потерь: нет tuple/numpy/enum


def test_item_with_overlay_has_no_bytes(make_plugin):
    item = _three_codes_item(make_plugin)

    _overlay(item)  # overlay в item обязателен, иначе проверка пуста
    _walk(item)


def test_item_without_frame_with_three_codes_fits_2048_bytes(make_plugin):
    item = _three_codes_item(make_plugin)

    _overlay(item)
    light = {k: v for k, v in item.items() if k != "frame"}
    size = len(json.dumps(light).encode("utf-8"))
    assert size <= 2048, f"item без кадра с 3 кодами = {size} Б (> 2048)"
