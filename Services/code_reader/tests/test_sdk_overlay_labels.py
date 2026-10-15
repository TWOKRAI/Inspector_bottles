# -*- coding: utf-8 -*-
"""Подписи overlay SDK-плагина задаёт регистр `labels` (рецепт): число, текст, якорь, сдвиг, группа, масштаб.

`_overlay` — чистая функция, её зовём напрямую на настоящем `SdkFrame`; один тест проходит весь путь
через конфиг плагина (как из рецепта): `labels` в конфиге -> item["overlay"].
"""

from __future__ import annotations

from Services.code_reader.plugin.sdk_plugin import _overlay
from Services.code_reader.tests import test_sdk_plugin as _base
from Services.code_reader.tests.test_sdk_plugin import _cmd, _collect, _raw
from Services.code_reader.tests.test_sdk_reader import FakeApi, bad_code as _bad_code, code as _code, frame as _frame

make_plugin = _base.make_plugin  # фикстура плагина на FakeApi

SQUARE = [[100, 100], [300, 100], [300, 300], [100, 300]]
COUNTERS = (5, 2, 1)


def _points(labels: list, codes: list | None = None, **kw) -> list[dict]:
    codes = [_code("QR-A", corners=SQUARE)] if codes is None else codes
    return _overlay(_frame(codes, **kw), COUNTERS, labels)["points"]


def test_empty_labels_give_no_points_but_frames_stay():
    ov = _overlay(_frame([_code("QR-A", corners=SQUARE)]), COUNTERS, [])

    assert ov["points"] == []
    assert len(ov["lines"]) == 4


def test_any_number_of_labels_each_becomes_a_point():
    labels = [
        {"per": "frame", "template": "one", "xy": [1, 2]},
        {"per": "frame", "template": "two", "xy": [3, 4]},
        {"per": "frame", "template": "three", "xy": [5, 6]},
        {"per": "code", "template": "{code}", "anchor": "corner0"},
    ]

    pts = _points(labels)

    assert [(p["label"], p["xy"]) for p in pts] == [
        ("one", [1, 2]),
        ("two", [3, 4]),
        ("three", [5, 6]),
        ("QR-A", [100, 100]),
    ]


def test_frame_label_template_keys_and_xy():
    pts = _points([{"per": "frame", "template": "{status}|{ok}/{no}/{bad}/{total}", "xy": [250, 400]}])

    assert [(p["label"], p["xy"]) for p in pts] == [("ok|5/2/1/8", [250, 400])]


def test_code_label_corner0_with_offset_and_per_code_repeat():
    other = [[400, 100], [500, 100], [500, 200], [400, 200]]
    labels = [{"per": "code", "template": "{code}", "anchor": "corner0", "dx": 15, "dy": -20}]

    pts = _points(labels, [_code("QR-A", corners=SQUARE), _code("QR-B", corners=other)])

    assert [(p["label"], p["xy"]) for p in pts] == [("QR-A", [115, 80]), ("QR-B", [415, 80])]


def test_code_label_anchor_frame_uses_absolute_xy():
    pts = _points([{"per": "code", "template": "{code}", "anchor": "frame", "xy": [7, 9], "dx": 1}])

    assert [p["xy"] for p in pts] == [[8, 9]]


def test_bad_code_text_is_its_status_like_before():
    pts = _points([{"per": "code", "template": "{code}"}], [_bad_code(corners=SQUARE)], no_read=1)

    assert [p["label"] for p in pts] == ["bad_code"]


def test_group_is_a_template_with_state():
    labels = [{"per": "code", "template": "{code}", "group": "code_text_{state}"}]

    ok = _points(labels)
    bad = _points(labels, [_bad_code(corners=SQUARE)], no_read=1)

    assert (ok[0]["group"], bad[0]["group"]) == ("code_text_ok", "code_text_bad")


def test_scale_and_group_pass_through_only_when_set():
    pts = _points(
        [
            {"per": "frame", "template": "a", "group": "status", "scale": 1.8},
            {"per": "frame", "template": "b"},
        ]
    )

    assert pts[0]["scale"] == 1.8 and pts[0]["group"] == "status"
    assert "scale" not in pts[1] and "group" not in pts[1]


def test_broken_template_does_not_raise_and_shows_itself():
    pts = _points([{"per": "frame", "template": "{nope} {", "xy": [0, 0]}])

    assert [p["label"] for p in pts] == ["{nope} {"]


def test_labels_from_plugin_config_reach_item_overlay(make_plugin):
    labels = [{"per": "frame", "template": "hello {ok}", "xy": [321, 123], "group": "g1"}]
    w = make_plugin(FakeApi(script=[_raw([_code("QR-A", corners=SQUARE)], 1)]), timeout_ms=20, labels=labels)
    assert _cmd(w, "take_device")["status"] == "ok"
    (item,) = _collect(w, 1)

    pts = item["overlay"]["points"]
    assert [(p["label"], p["xy"], p["group"]) for p in pts] == [("hello 1", [321, 123], "g1")]
