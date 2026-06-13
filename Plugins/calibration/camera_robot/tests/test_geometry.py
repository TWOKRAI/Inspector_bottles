"""Тесты geometry.py — математика калибровки P7 на синтетике.

Категории: (1) round-trip H без ленты; (2) ДВИЖУЩАЯСЯ лента (belt-компенсация —
ключевой кейс, доказывает знак); (3) belt_vector; (4) project_to_pick;
(5) вырожденные случаи; (6) стабильность order_points.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from Plugins.calibration.camera_robot.geometry import (
    apply_homography,
    belt_vector,
    compensate,
    fit_homography,
    order_points,
    project_to_pick,
    reprojection_error,
)

# --- Синтетическая сцена ---------------------------------------------------
# px-углы эталона в кадре (произвольная перспектива) и центр.
PX_CORNERS = [(100.0, 80.0), (540.0, 90.0), (560.0, 420.0), (90.0, 430.0)]  # TL, TR, BR, BL
PX_CENTER = (320.0, 250.0)
PX_ALL = PX_CORNERS + [PX_CENTER]  # индекс 4 = центр

# мм-углы (belt-fixed, оси робота) — задают истинную гомографию H_true.
MM_CORNERS = [(0.0, 0.0), (200.0, 0.0), (200.0, 150.0), (0.0, 150.0)]


def _h_true() -> np.ndarray:
    """Истинная гомография px→мм, фитнутая по 4 углам."""
    return fit_homography(PX_CORNERS, MM_CORNERS)


def _belt_fixed_all(h: np.ndarray) -> list[tuple[float, float]]:
    """belt-fixed мм для всех 5 точек (углы воспроизводят MM_CORNERS, центр — образ H)."""
    return [apply_homography(h, p) for p in PX_ALL]


def _assert_close(a, b, tol=1e-6):
    assert math.hypot(a[0] - b[0], a[1] - b[1]) < tol, f"{a} != {b} (tol={tol})"


# --- (1) round-trip без ленты ----------------------------------------------
def test_roundtrip_no_belt():
    h = _h_true()
    # Углы воспроизводятся точно.
    for px, mm in zip(PX_CORNERS, MM_CORNERS):
        _assert_close(apply_homography(h, px), mm)
    # reproj углов ≈ 0 by construction.
    err = reprojection_error(h, PX_CORNERS, MM_CORNERS)
    assert err["max_mm"] < 1e-6
    assert err["mean_mm"] < 1e-6


# --- (2) ДВИЖУЩАЯСЯ лента (ядро P7) -----------------------------------------
@pytest.mark.parametrize("belt_dir", [(1.0, 0.0), (0.6, 0.8), (-0.8, 0.6)])
def test_moving_belt_compensation_recovers_h(belt_dir):
    """Каждая точка замерена при своём энкодере; компенсация восстанавливает H_true."""
    h_true = _h_true()
    belt_fixed = _belt_fixed_all(h_true)
    e0 = 1000
    mm_per_count = 0.05
    enc_i = [1100, 1150, 1200, 1080, 1130]  # энкодеры касаний (центр — индекс 4)

    # Робот видит точки сдвинутыми лентой: mm = belt_fixed + (enc_i-E0)*scale*dir.
    mm_measured = []
    for bf, e in zip(belt_fixed, enc_i):
        shift = (e - e0) * mm_per_count
        mm_measured.append((bf[0] + shift * belt_dir[0], bf[1] + shift * belt_dir[1]))

    # Belt-компенсация должна вернуть belt_fixed обратно.
    mm_fixed = [compensate(mm, e, e0, mm_per_count, belt_dir) for mm, e in zip(mm_measured, enc_i)]
    for got, exp in zip(mm_fixed, belt_fixed):
        _assert_close(got, exp)

    # Фит по 4 углам очищенных точек → H_true; центр (5-я) валидирует.
    h_fit = fit_homography(PX_CORNERS, mm_fixed[:4])
    err = reprojection_error(h_fit, PX_ALL, mm_fixed, center_index=4)
    assert err["center_mm"] < 1e-6, f"центр поехал: {err['center_mm']}"
    assert err["max_mm"] < 1e-6


def test_naive_fit_without_compensation_fails():
    """Контроль: без belt-компенсации (наивный фит px→mm) центр уезжает — доказывает,
    что P7 необходима, а не косметика."""
    h_true = _h_true()
    belt_fixed = _belt_fixed_all(h_true)
    e0 = 1000
    mm_per_count = 0.05
    belt_dir = (1.0, 0.0)
    enc_i = [1100, 1150, 1200, 1080, 1130]
    mm_measured = []
    for bf, e in zip(belt_fixed, enc_i):
        shift = (e - e0) * mm_per_count
        mm_measured.append((bf[0] + shift * belt_dir[0], bf[1] + shift * belt_dir[1]))
    # Наивно фитим по СЫРЫМ mm (углы при разных энкодерах) — центр не сойдётся.
    h_bad = fit_homography(PX_CORNERS, mm_measured[:4])
    err = reprojection_error(h_bad, PX_ALL, mm_measured, center_index=4)
    assert err["center_mm"] > 0.1, "ожидали заметную ошибку центра без компенсации"


# --- (3) belt_vector --------------------------------------------------------
def test_belt_vector_known_values():
    r1 = (10.0, 20.0)
    enc_a, enc_b = 500, 700
    mm_per_count, belt_dir = 0.05, (0.6, 0.8)
    r2 = (r1[0] + (enc_b - enc_a) * mm_per_count * belt_dir[0], r1[1] + (enc_b - enc_a) * mm_per_count * belt_dir[1])
    got_scale, got_dir = belt_vector(r1, r2, enc_a, enc_b)
    assert abs(got_scale - mm_per_count) < 1e-9
    _assert_close(got_dir, belt_dir, tol=1e-9)


def test_belt_vector_negative_encoder_delta():
    """Направление при РОСТЕ энкодера не зависит от порядка передачи касаний."""
    r_late = (16.0, 28.0)
    r_early = (10.0, 20.0)
    scale, direction = belt_vector(r_late, r_early, 700, 500)  # enc убывает
    assert abs(scale - 0.05) < 1e-9
    _assert_close(direction, (0.6, 0.8), tol=1e-9)


# --- (4) project_to_pick ----------------------------------------------------
def test_project_to_pick_adds_belt_run():
    h = _h_true()
    px = PX_CENTER
    base = apply_homography(h, px)
    mm_per_count, belt_dir = 0.05, (1.0, 0.0)
    enc_cap, enc_pick = 1000, 1200
    got = project_to_pick(h, px, enc_cap, enc_pick, mm_per_count, belt_dir)
    expected = (base[0] + (enc_pick - enc_cap) * mm_per_count, base[1])
    _assert_close(got, expected)


# --- (5) вырожденные случаи -------------------------------------------------
def test_belt_vector_zero_encoder_delta_raises():
    with pytest.raises(ValueError):
        belt_vector((0.0, 0.0), (5.0, 5.0), 500, 500)


def test_belt_vector_no_displacement_raises():
    with pytest.raises(ValueError):
        belt_vector((3.0, 4.0), (3.0, 4.0), 500, 700)


def test_fit_homography_collinear_raises():
    collinear = [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0), (3.0, 3.0)]
    with pytest.raises(ValueError):
        fit_homography(collinear, MM_CORNERS)


def test_fit_homography_wrong_count_raises():
    with pytest.raises(ValueError):
        fit_homography(PX_CORNERS[:3], MM_CORNERS[:3])


def test_apply_homography_w_zero_raises():
    h = np.array([[1.0, 0.0, 5.0], [0.0, 1.0, 5.0], [1.0, 0.0, 0.0]])  # w = x
    with pytest.raises(ValueError):
        apply_homography(h, (0.0, 3.0))  # w = 0


def test_order_points_wrong_count_raises():
    with pytest.raises(ValueError):
        order_points([(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)])


# --- (6) order_points стабилен ----------------------------------------------
@pytest.mark.parametrize(
    "perm",
    [
        [(0, 0), (10, 0), (10, 8), (0, 8), (5, 4)],
        [(5, 4), (0, 8), (10, 8), (10, 0), (0, 0)],
        [(10, 8), (5, 4), (0, 0), (0, 8), (10, 0)],
    ],
)
def test_order_points_stable_under_shuffle(perm):
    corners, center = order_points([(float(x), float(y)) for x, y in perm])
    assert center == (5.0, 4.0)
    assert corners == [(0.0, 0.0), (10.0, 0.0), (10.0, 8.0), (0.0, 8.0)]  # TL, TR, BR, BL
