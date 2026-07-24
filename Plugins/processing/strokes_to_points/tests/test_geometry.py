"""Тесты геометрии strokes_to_points: прореживание и перевод px→мм."""

from __future__ import annotations

import numpy as np

from Plugins.processing.strokes_to_points import geometry


# --- Прореживание ---------------------------------------------------------- #


def test_simplify_dp_collapses_collinear() -> None:
    stroke = np.array([[float(i), 0.0] for i in range(11)])  # прямая 0..10
    out = geometry.simplify_dp(stroke, epsilon=1.0)
    assert len(out) == 2  # только концы


def test_resample_step_keeps_endpoints() -> None:
    stroke = np.array([[0.0, 0.0], [10.0, 0.0]])
    out = geometry.resample_step(stroke, step=2.5)
    assert len(out) == 5  # 0,2.5,5,7.5,10
    assert np.allclose(out[0], [0.0, 0.0])
    assert np.allclose(out[-1], [10.0, 0.0])


def test_reduce_angle_keeps_corner() -> None:
    leg1 = [[0.0, float(i)] for i in range(11)]  # вертикаль (0,0)..(0,10)
    leg2 = [[float(i), 10.0] for i in range(1, 11)]  # горизонталь до (10,10)
    stroke = np.array(leg1 + leg2)
    out = geometry.reduce_angle(stroke, angle_threshold_deg=45.0)
    # старт, угол, конец
    assert len(out) == 3
    assert np.allclose(out[0], [0.0, 0.0])
    assert np.allclose(out[1], [0.0, 10.0])
    assert np.allclose(out[2], [10.0, 10.0])


def test_sort_nearest_neighbor_orders_by_proximity() -> None:
    a = np.array([[0.0, 0.0], [1.0, 0.0]])
    far = np.array([[100.0, 100.0], [101.0, 100.0]])
    near = np.array([[2.0, 0.0], [3.0, 0.0]])
    ordered = geometry.sort_nearest_neighbor([a, far, near])
    # после a ближайший — near, не far
    assert np.allclose(ordered[1][0], near[0])


def test_sort_nearest_neighbor_matches_reference() -> None:
    """Вектор. версия совпадает со ссылочной жадной реализацией на случайных штрихах."""

    def _reference(strokes: list[np.ndarray]) -> list[np.ndarray]:
        if len(strokes) <= 1:
            return strokes
        ordered = [strokes[0]]
        remaining = list(strokes[1:])
        cur = ordered[-1][-1]
        while remaining:
            starts = np.array([s[0] for s in remaining])
            idx = int(np.argmin(np.linalg.norm(starts - cur, axis=1)))
            ordered.append(remaining.pop(idx))
            cur = ordered[-1][-1]
        return ordered

    rng = np.random.default_rng(0)
    for _ in range(20):
        n = int(rng.integers(1, 60))
        strokes = [rng.uniform(0, 640, (int(rng.integers(2, 12)), 2)) for _ in range(n)]
        ref = _reference([s.copy() for s in strokes])
        got = geometry.sort_nearest_neighbor([s.copy() for s in strokes])
        assert len(got) == len(ref)
        assert all(np.array_equal(x, y) for x, y in zip(got, ref))


# --- px → мм + перо -------------------------------------------------------- #


def test_polylines_to_points_pen_structure() -> None:
    poly = np.array([[10.0, 20.0], [30.0, 40.0], [50.0, 60.0]])
    pts = geometry.polylines_to_points([poly], height=100, scale_x=0.1, scale_y=0.1, flip_y=False)
    assert len(pts) == 3
    assert pts[0]["pen"] == 0  # подвод
    assert pts[1]["pen"] == 1 and pts[2]["pen"] == 1
    assert pts[0]["x_mm"] == 1.0 and pts[0]["y_mm"] == 2.0


def test_polylines_to_points_flip_y() -> None:
    poly = np.array([[10.0, 20.0], [30.0, 40.0]])
    pts = geometry.polylines_to_points([poly], height=100, scale_x=0.1, scale_y=0.1, flip_y=True)
    # y_src = (100-1-20) = 79 → 7.9
    assert abs(pts[0]["y_mm"] - 7.9) < 1e-6


def test_polylines_to_points_zone_mode() -> None:
    poly = np.array([[0.0, 0.0], [100.0, 100.0]])  # из угла в угол кадра 100×100
    pts = geometry.polylines_to_points(
        [poly],
        height=100,
        width=100,
        zone_mode=True,
        zone_x0=10.0,
        zone_y0=20.0,
        zone_x1=110.0,
        zone_y1=220.0,
    )
    # px(0,0) → ЛВ угол зоны (10,20); px(100,100) → ПН угол (110,220)
    assert abs(pts[0]["x_mm"] - 10.0) < 1e-6 and abs(pts[0]["y_mm"] - 20.0) < 1e-6
    assert abs(pts[1]["x_mm"] - 110.0) < 1e-6 and abs(pts[1]["y_mm"] - 220.0) < 1e-6


def test_polylines_to_points_max_points_truncates_by_stroke() -> None:
    poly_a = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]])  # 3 точки
    poly_b = np.array([[5.0, 5.0], [6.0, 5.0], [7.0, 5.0]])  # 3 точки
    pts = geometry.polylines_to_points([poly_a, poly_b], height=50, max_points=4)
    # poly_a (3) влезает; poly_b (ещё 3) превысит 4 → отброшен целиком
    assert len(pts) == 3


def test_extract_polylines_on_square_mask() -> None:
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[20:80, 20:80] = 255
    polys = geometry.extract_polylines(mask, centerline=False, reduce_mode="dp", min_stroke_len=5.0)
    assert len(polys) >= 1
    assert polys[0].ndim == 2 and polys[0].shape[1] == 2


# --- Центральная линия (скелет + трассировка) ---


def _total_len(polys: list[np.ndarray]) -> float:
    return float(sum(np.sum(np.linalg.norm(np.diff(p, axis=0), axis=1)) for p in polys if len(p) >= 2))


def test_skeletonize_thins_thick_line() -> None:
    mask = np.zeros((40, 80), dtype=np.uint8)
    mask[18:23, 10:70] = 255  # толстая горизонтальная линия (5px × 60px)
    skel = geometry.skeletonize_mask(mask)
    # скелет тоньше оригинала: белых пикселей заметно меньше
    assert int((skel > 0).sum()) < int((mask > 0).sum()) // 2


def test_trace_skeleton_single_horizontal_line() -> None:
    skel = np.zeros((40, 80), dtype=np.uint8)
    skel[20, 10:70] = 255  # уже 1px линия
    polys = geometry.trace_skeleton(skel)
    assert len(polys) == 1  # одна линия, не петля
    # длина ≈ 59 (по центру), не удвоена
    assert 55 <= _total_len(polys) <= 62


def test_centerline_shorter_than_contour_on_thick_line() -> None:
    mask = np.zeros((40, 80), dtype=np.uint8)
    mask[16:25, 10:70] = 255  # толстая линия 9px × 60px
    center = geometry.extract_polylines(mask, centerline=True, reduce_mode="none", min_stroke_len=2.0)
    contour = geometry.extract_polylines(mask, centerline=False, reduce_mode="none", min_stroke_len=2.0)
    # центральная линия — ОДНА полилиния вдоль центра, короче обводки контура
    assert len(center) == 1
    assert _total_len(center) < _total_len(contour)
    assert 40 <= _total_len(center) <= 65
