# multiprocess_prototype/tests/test_post_processing_params.py
"""Параметры post_processing_regions без Qt."""

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

from multiprocess_prototype.frontend.widgets.post_processing_widget.params import (
    merge_post_processing_payload,
    normalize_post_processing_payload,
    normalize_region_entry,
    regions_to_table_rows,
)


def test_normalize_region_entry():
    r = normalize_region_entry({"name": "a", "x1": 1.2, "enabled": 0})
    assert r["name"] == "a"
    assert r["x1"] == 1
    assert r["enabled"] is False


def test_regions_to_table_rows():
    rows = regions_to_table_rows([{"name": "r", "x1": 0, "y1": 1, "x2": 10, "y2": 2}])
    assert rows[0]["coords"] == "(0,1)-(10,2)"
    assert rows[0]["region_id"] == "r"


def test_merge_post_processing_payload():
    p = merge_post_processing_payload(
        {"cam1": [{"name": "a", "x1": 0, "y1": 0, "x2": 1, "y2": 1}]},
    )
    assert p["cam1"][0]["name"] == "a"


def test_normalize_nested():
    n = normalize_post_processing_payload(
        {"c1": [{"name": "x", "x1": 1, "y1": 2, "x2": 3, "y2": 4}]},
    )
    assert n["c1"][0]["x2"] == 3


def test_normalize_invalid_empty():
    assert normalize_post_processing_payload(None) == {}
    assert normalize_post_processing_payload([]) == {}
