# multiprocess_prototype/tests/test_cropped_regions_params.py
"""Логика rect и payload для вкладки регионов обрезки."""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_paths() -> None:
    proto = Path(__file__).resolve().parent.parent
    root = proto.parent
    mods = root / "multiprocess_framework" / "modules"
    for p in (str(root), str(proto), str(mods)):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_paths()

from multiprocess_prototype.frontend.widgets.cropped_regions_widget.params import (
    CROPPED_PARAM_KEYS,
    CroppedParamKey,
    coords_list_from_params,
    merge_crop_regions_payload,
    normalize_crop_regions_payload,
    params_from_coords_list,
    params_to_rect,
    parse_int_coordinate,
    rect_to_params,
    region_entry_from_params,
    regions_to_table_rows,
)


def test_params_to_rect():
    r = params_to_rect({"x": 10, "y": 5, "width": 100, "height": 200})
    assert r == {"x": 10, "y": 5, "width": 100, "height": 200}


def test_rect_to_params_roundtrip():
    rect = {"x": 5, "y": 7, "width": 100, "height": 48}
    p = rect_to_params(rect, None)
    assert params_to_rect(p) == rect


def test_coords_list_roundtrip():
    p = {"x": 1, "y": 2, "width": 3, "height": 4}
    lst = coords_list_from_params(p)
    assert coords_list_from_params(params_from_coords_list(lst)) == lst


def test_region_entry_from_params():
    e = region_entry_from_params({"x": 0, "width": 50, "y": 0, "height": 10})
    assert e["rect"]["width"] == 50
    assert e["rect"]["height"] == 10


def test_regions_to_table_rows():
    rows = regions_to_table_rows({"r1": [0, 1, 10, 3]})
    assert len(rows) == 1
    assert rows[0]["region_id"] == "r1"
    assert rows[0]["width"] == 10


def test_merge_crop_regions_payload():
    payload = merge_crop_regions_payload(
        {"cam1": {"a": [0, 2, 10, 1]}},
    )
    assert "cam1" in payload
    assert payload["cam1"]["a"] == [0, 2, 10, 1]


def test_normalize_nested():
    n = normalize_crop_regions_payload(
        {"c1": {"r": [1, 2, 3, 4]}},
        default_camera="default",
    )
    assert n["c1"]["r"] == [1, 2, 3, 4]


def test_normalize_legacy_flat():
    n = normalize_crop_regions_payload(
        {
            "old": {
                "params": {"x_min": 0, "x_max": 10, "height": 3, "y_delta": 1},
                "rect": {},
            }
        },
        default_camera="default",
    )
    assert "default" in n
    assert n["default"]["old"] == [0, 1, 10, 3]


def test_cropped_param_key_enum_covers_keys():
    assert len(CROPPED_PARAM_KEYS) == len(CroppedParamKey)
    assert CroppedParamKey.X.value in CROPPED_PARAM_KEYS


def test_parse_int_coordinate():
    assert parse_int_coordinate("10") == 10
    assert parse_int_coordinate("  3.7 ") == 4
    assert parse_int_coordinate("") == 0
    assert parse_int_coordinate(None) == 0
