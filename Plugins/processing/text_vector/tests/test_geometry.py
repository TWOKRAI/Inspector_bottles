"""Тесты геометрии text_vector: раскладка, матрица 2×2, → draw_points."""

from __future__ import annotations

import math

from Plugins.processing.text_vector import geometry, strokes_font


def test_layout_advances_left_to_right() -> None:
    # Два символа 'HH' (одинаковая ширина) — второй сдвинут вправо ровно на advance*scale.
    size = 60.0
    scale = size / strokes_font.CAP
    polys, skipped = geometry.layout_text("HH", size)
    assert skipped == []
    minx, _, maxx, _ = geometry.bbox(polys)
    assert minx == 0.0  # первый глиф у origin
    # Ширина блока ≈ advance('H')*scale + ширина глифа второго.
    assert maxx > strokes_font.advance("H") * scale  # второй символ дальше первого


def test_unknown_char_skipped_not_breaking() -> None:
    polys, skipped = geometry.layout_text("A☺B", 40.0)
    assert "☺" in skipped
    assert polys  # A и B разложены, раскладка не порвалась


def test_lowercase_maps_to_uppercase() -> None:
    up, _ = geometry.layout_text("ПРИВЕТ", 40.0)
    lo, _ = geometry.layout_text("привет", 40.0)
    assert len(up) == len(lo)  # строчные нормализуются в прописные (тот же глиф)


def test_size_px_sets_cap_height() -> None:
    # Высота прописной 'I' (вертикальный штрих 0..CAP) = size_px.
    polys, _ = geometry.layout_text("I", 100.0)
    _, miny, _, maxy = geometry.bbox(polys)
    assert abs((maxy - miny) - 100.0) < 1e-6


def test_apply_transform_rotation_90() -> None:
    # Точка (cx+1, cy) после поворота на 90° (Y вниз) → (cx, cy+1) [по часовой].
    poly = [[(0.0, 0.0), (2.0, 0.0)]]  # центр в (1,0)
    out = geometry.apply_transform(poly, scale=1.0, rotation_deg=90.0, pos_x=0.0, pos_y=0.0)
    (x0, y0), (x1, y1) = out[0]
    # (0,0) относительно центра (1,0) = (-1,0) → поворот 90° → (0,-1) → +pos(0,0)
    assert abs(x0 - 0.0) < 1e-9 and abs(y0 - (-1.0)) < 1e-9
    assert abs(x1 - 0.0) < 1e-9 and abs(y1 - 1.0) < 1e-9


def test_apply_transform_scale_and_pos() -> None:
    poly = [[(0.0, 0.0), (2.0, 0.0)]]  # центр (1,0), полуширина 1
    out = geometry.apply_transform(poly, scale=3.0, rotation_deg=0.0, pos_x=100.0, pos_y=50.0)
    (x0, y0), (x1, y1) = out[0]
    assert (x0, y0) == (97.0, 50.0)  # -1*3 + 100
    assert (x1, y1) == (103.0, 50.0)  # +1*3 + 100


def test_heart_is_closed_single_polyline() -> None:
    polys = geometry.heart_polylines(100.0)
    assert len(polys) == 1
    first, last = polys[0][0], polys[0][-1]
    assert math.dist(first, last) < 1e-6  # замкнута


def test_polylines_to_draw_points_pen_sequence() -> None:
    polys = [[(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)], [(5.0, 5.0), (6.0, 6.0)]]
    pts = geometry.polylines_to_draw_points(polys)
    assert [p["pen"] for p in pts] == [0, 1, 1, 0, 1]  # подвод (0) в начале каждой полилинии


def test_build_element_heart_ignores_text() -> None:
    pts, skipped = geometry.build_element(
        element="heart",
        text="мусор",
        size_px=80.0,
        tracking_px=0.0,
        scale=1.0,
        rotation_deg=0.0,
        pos_x=320.0,
        pos_y=240.0,
    )
    assert skipped == []
    assert pts and pts[0]["pen"] == 0
