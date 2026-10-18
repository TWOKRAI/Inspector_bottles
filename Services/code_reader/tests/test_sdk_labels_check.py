# -*- coding: utf-8 -*-
"""Раунд 3: прямые тесты ``_check_labels`` / ``_label_point`` (формат сообщения, утечка значений, крайние входы).

Приёмочные тесты тестера (``test_sdk_labels_robust.py``) идут через плагин на фейке; здесь — точный текст
сообщения configure и входы, которых там нет (inf, bool, строковое число в scale).
"""

from __future__ import annotations

import pytest

from Services.code_reader.plugin.sdk_plugin import _check_labels, _label_point
from Services.code_reader.tests import test_sdk_plugin as _base
from Services.code_reader.tests.test_sdk_plugin import _cmd, _collect, _raw
from Services.code_reader.tests.test_sdk_reader import FakeApi

make_plugin = _base.make_plugin  # фикстура плагина на FakeApi


def test_message_format_index_field_exception_name_without_value():
    labels = [
        {"per": "frame", "template": "ok", "xy": [1, 2]},
        {"per": "frame", "template": "t", "xy": [1, 2], "dx": "СЕКРЕТ5"},
        {"per": "frame", "template": "t", "xy": [3, 4], "scale": "СЕКРЕТ_big"},
    ]
    msg = _check_labels(labels)
    assert msg == "labels[1]: dx TypeError; labels[2]: scale ValueError"
    assert "СЕКРЕТ" not in msg


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ({"per": "frame", "xy": [1]}, "labels[0]: xy ValueError"),
        ({"per": "frame", "xy": None}, "labels[0]: xy TypeError"),
        ({"per": "frame", "xy": "ab"}, "labels[0]: xy TypeError"),
        ({"per": "frame", "xy": [float("inf"), 0]}, "labels[0]: xy ValueError"),
        ({"per": "frame", "xy": [2**31, 0]}, "labels[0]: xy ValueError"),
        ({"per": "frame", "xy": [2**30, 0]}, "labels[0]: xy ValueError"),  # граница: 2**30 уже плохо
        ({"per": "frame", "xy": [-(2**30) - 1, 0]}, "labels[0]: xy ValueError"),
        ({"per": "frame", "xy": [10**400, 2]}, "labels[0]: xy ValueError"),  # огромный int: без OverflowError
        ({"per": "frame", "xy": [1, 2], "dx": 10**400}, "labels[0]: dx ValueError"),
        ({"per": "frame", "xy": [1, 2], "dx": -(10**400)}, "labels[0]: dx ValueError"),
        ({"per": "frame", "xy": [1, 2], "dy": 2**1024}, "labels[0]: dy ValueError"),
        ({"per": "frame", "xy": [1, 2], "scale": 50.5}, "labels[0]: scale ValueError"),  # потолок 50
        ({"per": "frame", "xy": [1, 2], "scale": 1e9}, "labels[0]: scale ValueError"),
        ({"per": "frame", "xy": [1, 2], "scale": 10**400}, "labels[0]: scale OverflowError"),
        ({"per": "frame", "xy": [1e300, 0]}, "labels[0]: xy ValueError"),
        ({"per": "frame", "xy": [-(2**31) - 1, 0]}, "labels[0]: xy ValueError"),
        ({"per": "frame", "xy": [2**30 - 10, 0], "dx": 10}, "labels[0]: xy ValueError"),  # сумма вышла за предел
        ({"per": "frame", "xy": [1, 2], "dx": 1e12}, "labels[0]: dx ValueError"),
        ({"per": "frame", "xy": [1, 2], "dx": float("nan")}, "labels[0]: dx ValueError"),
        ({"per": "frame", "xy": [1, 2], "dy": float("inf")}, "labels[0]: dy ValueError"),
        ({"per": "frame", "xy": [1, 2], "scale": float("nan")}, "labels[0]: scale ValueError"),
        ({"per": "frame", "xy": [1, 2], "scale": float("inf")}, "labels[0]: scale ValueError"),
        ({"per": "frame", "xy": [1, 2], "scale": "nan"}, "labels[0]: scale ValueError"),
        ({"per": "frame", "xy": [1, 2], "scale": True}, "labels[0]: scale TypeError"),
        ({"per": "fram", "xy": [1, 2]}, "labels[0]: per ValueError"),
        ({"per": "frame", "anchor": "corner", "xy": [1, 2]}, "labels[0]: anchor ValueError"),
        ({"per": "code", "anchor": ["x"]}, "labels[0]: anchor ValueError"),
        ({"per": "frame", "xy": [1, 2], "dy": True}, "labels[0]: dy TypeError"),
        ({"per": "code", "dx": "5"}, "labels[0]: dx TypeError"),
    ],
)
def test_bad_field_is_named(spec, expected):
    assert _check_labels([spec]) == expected


def test_non_dict_item_is_reported_by_index_and_type_only():
    assert _check_labels([{"per": "frame", "xy": [1, 2]}, "oops", None]) == (
        "labels[1]: не dict (str); labels[2]: не dict (NoneType)"
    )


@pytest.mark.parametrize(
    "labels",
    [
        [],
        [{"per": "frame", "template": "{ok[0]}", "xy": [1, 2]}],
        [{"per": "frame", "xy": [1, 2], "scale": "1.5"}],
        [{"per": "frame", "xy": [2**30 - 10, 0]}, {"per": "frame", "xy": [-(2**30), 0]}],  # границы допустимы
        [{"per": "frame", "xy": [1, 2], "scale": 50}],  # потолок scale включительно
        # frame + corner0: не рисуется (угла нет), но конфиг не ошибочен — поведение валидных пар не менялось
        [{"per": "frame", "anchor": "corner0"}],
    ],
)
def test_valid_labels_give_empty_message(labels):
    assert _check_labels(labels) == ""


@pytest.mark.parametrize(
    "spec",
    [
        {"per": "frame", "xy": [2**31, 0]},
        {"per": "frame", "xy": [1, 2], "dx": 1e12},
        {"per": "frame", "xy": [1, 2], "scale": "nan"},
        {"per": "fram", "xy": [1, 2]},
        {"per": "frame", "anchor": "corner", "xy": [1, 2]},
    ],
)
def test_label_point_skips_what_check_labels_reports(spec):
    """Единый путь: что называет configure, то и пропускает produce()."""
    assert _check_labels([spec]) != ""
    assert _label_point(spec, {}, [[0, 0]]) is None


def test_format_survives_overflow_and_overlay_keeps_the_label():
    from Services.code_reader.core.result import ReadStatus
    from Services.code_reader.core.sdk_frame import SdkFrame
    from Services.code_reader.plugin.sdk_plugin import _format, _overlay

    assert _format("{ok:c}", {"ok": 1114112}) == "{ok:c}"  # OverflowError
    frame = SdkFrame(
        trigger_index=1,
        frame_num=1,
        width=1,
        height=1,
        pixel_format="x",
        image=b"",
        codes=(),
        no_read_num=0,
        status=ReadStatus.NO_CODE,
    )
    out = _overlay(frame, (1114112, 0, 0), [{"per": "frame", "template": "{ok:c}", "xy": [5, 6]}])
    assert [(p["label"], p["xy"]) for p in out["points"]] == [("{ok:c}", [5, 6])]


def test_label_point_returns_none_instead_of_raising_and_keeps_numeric_string_scale():
    assert _label_point({"per": "frame", "xy": [1, 2], "dx": "5"}, {}, []) is None
    point = _label_point({"per": "frame", "xy": [1, 2], "template": "t", "scale": "1.5"}, {}, [])
    assert point == {"xy": [1, 2], "label": "t", "scale": 1.5}


# --------------------------------------------------------------------------
# Журнал: по одной записи на плагин, а не на кадр
# --------------------------------------------------------------------------


def _errors_about(w, needle: str) -> list[str]:
    return [e["msg"] for e in w.ctx.services.logs if e["level"] == "ERROR" and needle in e["msg"]]


def test_bad_labels_error_is_logged_exactly_once_over_100_produce_calls_without_value(make_plugin):
    bad = {"per": "frame", "template": "t", "xy": [1, 2], "dx": "СЕКРЕТ5"}
    api = FakeApi()
    w = make_plugin(api, timeout_ms=20, labels=[bad])
    assert _cmd(w, "take_device")["status"] == "ok"
    assert len(_errors_about(w, "плохие подписи labels")) == 1  # после configure
    for trig in range(1, 101):
        api.script.append(_raw([], trig))
        assert len(_collect(w, 1)) == 1
    entries = _errors_about(w, "плохие подписи labels")
    assert len(entries) == 1, entries
    assert "labels[0]: dx TypeError" in entries[0]
    assert "СЕКРЕТ" not in entries[0]


def test_overlay_failure_keeps_frames_and_logs_once_over_100_frames(make_plugin, monkeypatch):
    """M1: отказ _overlay не роняет produce() и не теряет кадры; ERROR один на плагин, не на кадр."""
    from Services.code_reader.plugin import sdk_plugin

    def boom(*_a, **_kw):
        raise RuntimeError("СЕКРЕТ_overlay")

    monkeypatch.setattr(sdk_plugin, "_overlay", boom)
    api = FakeApi()
    w = make_plugin(api, timeout_ms=20)
    assert _cmd(w, "take_device")["status"] == "ok"
    for trig in range(1, 101):
        api.script.append(_raw([], trig))
        (item,) = _collect(w, 1)
        assert item["trigger_index"] == trig
        assert item["overlay"] == {"lines": [], "points": []}
    entries = _errors_about(w, "overlay не построен")
    assert len(entries) == 1, entries
    assert "RuntimeError" in entries[0] and "СЕКРЕТ" not in entries[0]


def test_huge_int_label_does_not_break_configure(make_plugin):
    """R2-1: ``dx: 10**400`` раньше бросал OverflowError из math.isfinite прямо в configure."""
    good = {"per": "frame", "template": "A", "xy": [10, 20]}
    w = make_plugin(FakeApi(), timeout_ms=20, labels=[good, {"per": "frame", "xy": [1, 2], "dx": 10**400}])
    err = w.plugin._reg.last_error or _status_error(w)
    assert "labels[1]" in err and "labels[0]" not in err, err


def _status_error(w) -> str:
    from Services.code_reader.tests.test_sdk_plugin import _status

    return _status(w)["last_error"] or ""


@pytest.mark.parametrize(
    "spec",
    [
        {"per": "frame", "template": "A", "xy": [2**30 - 10, 2**30 - 10], "scale": 50},
        {"per": "frame", "template": "A", "xy": [-(2**30), -(2**30)], "scale": 50},
    ],
)
def test_accepted_boundary_values_are_drawable_by_real_cv2(spec):
    """Пределы подобраны по настоящему cv2: всё, что проходит проверку, рисуется так же, как в overlay_draw."""
    import cv2
    import numpy as np

    assert _check_labels([spec]) == ""
    point = _label_point(spec, {}, [])
    x, y = point["xy"]
    canvas = np.zeros((64, 64, 3), np.uint8)
    cv2.circle(canvas, (x, y), 3, (255, 255, 255), -1)
    cv2.putText(
        canvas,
        point["label"],
        (x + 6, y - 6),
        cv2.FONT_HERSHEY_SIMPLEX,
        point["scale"],
        (255, 255, 255),
        max(1, round(point["scale"] * 2.5)),
        cv2.LINE_AA,
    )
