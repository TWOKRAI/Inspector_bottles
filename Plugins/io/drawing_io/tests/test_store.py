"""Тесты store: round-trip сохранения/загрузки карты точек (+ PNG)."""

from __future__ import annotations

import numpy as np

from Plugins.io.drawing_io import store


def test_save_load_roundtrip_points_bounds_meta(tmp_path) -> None:
    points = [{"x_mm": 1.5, "y_mm": -2.0, "pen": 0}, {"x_mm": 3.0, "y_mm": 4.0, "pen": 1}]
    bounds = [0.0, 0.0, 200.0, 200.0]
    meta = {"created": "2026-06-17", "points": 2}
    jp = store.save(str(tmp_path), "draw1", points, bounds=bounds, meta=meta)
    assert jp.endswith("draw1.json")

    pts, b, m, img = store.load(jp)
    assert pts == points  # точки лосслесс
    assert b == bounds
    assert m["points"] == 2
    assert img is None  # без картинки


def test_save_writes_png_sibling(tmp_path) -> None:
    img = np.zeros((20, 30, 3), dtype=np.uint8)
    img[:] = 128
    jp = store.save(str(tmp_path), "draw2", [{"x_mm": 0.0, "y_mm": 0.0, "pen": 1}], image_bgr=img)
    _pts, _b, _m, img_path = store.load(jp)
    assert img_path is not None and img_path.endswith("draw2.png")
    import cv2

    loaded = cv2.imread(img_path)
    assert loaded is not None and loaded.shape == (20, 30, 3)


def test_save_skips_malformed_points(tmp_path) -> None:
    pts = [{"x_mm": 1.0, "y_mm": 2.0}, "junk", {"no": 1}]
    jp = store.save(str(tmp_path), "draw3", pts)
    out, _b, _m, _i = store.load(jp)
    assert out == [{"x_mm": 1.0, "y_mm": 2.0, "pen": 1}]  # мусор отброшен, дефолт pen


def test_save_creates_dir(tmp_path) -> None:
    sub = tmp_path / "nested" / "drawings"
    jp = store.save(str(sub), "d", [{"x_mm": 0.0, "y_mm": 0.0, "pen": 1}])
    import os

    assert os.path.exists(jp)
