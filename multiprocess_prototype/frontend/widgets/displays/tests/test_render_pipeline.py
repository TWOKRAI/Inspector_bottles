# -*- coding: utf-8 -*-
"""test_render_pipeline.py — Unit-тесты конвейера трансформаций кадра.

Тесты не требуют Qt — только numpy/cv2. Проверяют:
    1.  crop меняет shape
    2.  scale меняет размер
    3.  rotate 90 меняет w/h местами
    4.  flip корректен (horizontal / vertical / both)
    5.  run_pipeline применяет crop→scale→rotate→flip в правильном порядке
    6.  Входной array НЕ мутируется (assert исходный array не изменился)
    7.  crop за границами → clamp (не падает)
    8.  crop=None → passthrough (shape не меняется)
    9.  scale=10 (минимум) — не падает
    10. GRAY (2D) кадр проходит через полный pipeline
    11. rotate 90 на неквадратном кадре — w/h меняются местами

Refs: plans/displays-in-recipe/plan.md, Task 4.1
"""

from __future__ import annotations

import numpy as np

from multiprocess_prototype.frontend.widgets.displays.render_pipeline import (
    apply_crop,
    apply_flip,
    apply_rotate,
    apply_scale,
    run_pipeline,
)


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def _bgr(h: int = 100, w: int = 200) -> np.ndarray:
    """Создать синтетический BGR-кадр заданного размера."""
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    # Наполним различимыми значениями для проверки отражений
    arr[:, : w // 2] = [64, 128, 255]  # левая половина
    arr[:, w // 2 :] = [255, 128, 64]  # правая половина
    return arr


def _gray(h: int = 100, w: int = 200) -> np.ndarray:
    """Создать синтетический GRAY-кадр (2D) заданного размера."""
    arr = np.zeros((h, w), dtype=np.uint8)
    arr[: h // 2, :] = 128  # верхняя половина
    return arr


# ---------------------------------------------------------------------------
# Test 1: apply_crop меняет shape
# ---------------------------------------------------------------------------


def test_crop_changes_shape():
    """apply_crop с корректным crop меняет shape кадра."""
    arr = _bgr(100, 200)
    result = apply_crop(arr, {"x": 10, "y": 20, "w": 50, "h": 30})
    assert result.shape == (30, 50, 3), f"Ожидается (30, 50, 3), получено {result.shape}"


# ---------------------------------------------------------------------------
# Test 2: apply_scale меняет размер
# ---------------------------------------------------------------------------


def test_scale_changes_size_50pct():
    """apply_scale(50) уменьшает размер вдвое."""
    arr = _bgr(100, 200)
    result = apply_scale(arr, 50)
    assert result.shape == (50, 100, 3), f"Ожидается (50, 100, 3), получено {result.shape}"


def test_scale_changes_size_200pct():
    """apply_scale(200) увеличивает размер вдвое."""
    arr = _bgr(100, 200)
    result = apply_scale(arr, 200)
    assert result.shape == (200, 400, 3), f"Ожидается (200, 400, 3), получено {result.shape}"


# ---------------------------------------------------------------------------
# Test 3: apply_rotate 90 меняет w/h местами
# ---------------------------------------------------------------------------


def test_rotate_90_swaps_dimensions():
    """apply_rotate(90) на неквадратном кадре меняет w/h местами."""
    arr = _bgr(100, 200)  # h=100, w=200
    result = apply_rotate(arr, 90)
    # После поворота 90° clockwise: h=200, w=100
    assert result.shape == (200, 100, 3), f"Ожидается (200, 100, 3), получено {result.shape}"


def test_rotate_270_swaps_dimensions():
    """apply_rotate(270) тоже меняет w/h местами."""
    arr = _bgr(100, 200)
    result = apply_rotate(arr, 270)
    assert result.shape == (200, 100, 3), f"Ожидается (200, 100, 3), получено {result.shape}"


def test_rotate_180_preserves_dimensions():
    """apply_rotate(180) не меняет размеры."""
    arr = _bgr(100, 200)
    result = apply_rotate(arr, 180)
    assert result.shape == (100, 200, 3), f"Ожидается (100, 200, 3), получено {result.shape}"


def test_rotate_0_preserves_dimensions():
    """apply_rotate(0) → copy с теми же размерами."""
    arr = _bgr(100, 200)
    result = apply_rotate(arr, 0)
    assert result.shape == arr.shape


# ---------------------------------------------------------------------------
# Test 4: apply_flip корректен
# ---------------------------------------------------------------------------


def test_flip_horizontal_mirrors_columns():
    """apply_flip('horizontal') зеркалит по вертикальной оси (меняет колонки)."""
    arr = _bgr(100, 200)
    result = apply_flip(arr, "horizontal")
    # Правая половина исходника (255,128,64) должна оказаться слева
    assert np.array_equal(result[:, 0], arr[:, -1])
    assert np.array_equal(result[:, -1], arr[:, 0])


def test_flip_vertical_mirrors_rows():
    """apply_flip('vertical') зеркалит по горизонтальной оси (меняет строки)."""
    arr = _bgr(100, 200)
    result = apply_flip(arr, "vertical")
    assert np.array_equal(result[0], arr[-1])
    assert np.array_equal(result[-1], arr[0])


def test_flip_both():
    """apply_flip('both') = horizontal + vertical."""
    arr = _bgr(100, 200)
    h_then_v = apply_flip(apply_flip(arr, "horizontal"), "vertical")
    both = apply_flip(arr, "both")
    assert np.array_equal(both, h_then_v)


def test_flip_none_returns_copy():
    """apply_flip('none') возвращает копию без изменений."""
    arr = _bgr(100, 200)
    result = apply_flip(arr, "none")
    assert np.array_equal(result, arr)
    # Убеждаемся, что это копия, а не тот же объект
    assert result is not arr


# ---------------------------------------------------------------------------
# Test 5: run_pipeline применяет трансформации в правильном порядке
# ---------------------------------------------------------------------------


def test_run_pipeline_order_crop_then_scale():
    """run_pipeline: crop меняет область, затем scale применяется к ней."""
    arr = _bgr(100, 200)
    # crop 50x50 из (0,0), затем scale 200% → 100x100
    params = {"crop": {"x": 0, "y": 0, "w": 50, "h": 50}, "scale": 200, "rotate": 0, "flip": "none"}
    result = run_pipeline(arr, params)
    assert result.shape == (100, 100, 3), f"Ожидается (100, 100, 3), получено {result.shape}"


def test_run_pipeline_order_scale_then_rotate():
    """run_pipeline: scale применяется до rotate — результирующий shape корректен."""
    arr = _bgr(100, 200)  # h=100, w=200
    # scale 50% → (50, 100), rotate 90 → (100, 50)
    params = {"crop": None, "scale": 50, "rotate": 90, "flip": "none"}
    result = run_pipeline(arr, params)
    assert result.shape == (100, 50, 3), f"Ожидается (100, 50, 3), получено {result.shape}"


def test_run_pipeline_all_noop():
    """run_pipeline с дефолтными параметрами (crop=None, scale=100, rotate=0, flip=none)."""
    arr = _bgr(100, 200)
    result = run_pipeline(arr, {"crop": None, "scale": 100, "rotate": 0, "flip": "none"})
    assert result.shape == arr.shape
    assert np.array_equal(result, arr)


def test_run_pipeline_none_params():
    """run_pipeline(arr, None) — params=None использует дефолты, не падает."""
    arr = _bgr(100, 200)
    result = run_pipeline(arr, None)
    assert result.shape == arr.shape


# ---------------------------------------------------------------------------
# Test 6: Входной array НЕ мутируется
# ---------------------------------------------------------------------------


def test_input_not_mutated_by_crop():
    """apply_crop не мутирует входной array."""
    arr = _bgr(100, 200)
    original = arr.copy()
    apply_crop(arr, {"x": 10, "y": 10, "w": 50, "h": 50})
    assert np.array_equal(arr, original), "apply_crop мутировал входной array"


def test_input_not_mutated_by_scale():
    """apply_scale не мутирует входной array."""
    arr = _bgr(100, 200)
    original = arr.copy()
    apply_scale(arr, 50)
    assert np.array_equal(arr, original), "apply_scale мутировал входной array"


def test_input_not_mutated_by_rotate():
    """apply_rotate не мутирует входной array."""
    arr = _bgr(100, 200)
    original = arr.copy()
    apply_rotate(arr, 90)
    assert np.array_equal(arr, original), "apply_rotate мутировал входной array"


def test_input_not_mutated_by_flip():
    """apply_flip не мутирует входной array."""
    arr = _bgr(100, 200)
    original = arr.copy()
    apply_flip(arr, "horizontal")
    assert np.array_equal(arr, original), "apply_flip мутировал входной array"


def test_input_not_mutated_by_run_pipeline():
    """run_pipeline не мутирует входной array."""
    arr = _bgr(100, 200)
    original = arr.copy()
    run_pipeline(arr, {"crop": {"x": 5, "y": 5, "w": 40, "h": 40}, "scale": 150, "rotate": 90, "flip": "both"})
    assert np.array_equal(arr, original), "run_pipeline мутировал входной array"


# ---------------------------------------------------------------------------
# Test 7: crop за границами → clamp (не падает)
# ---------------------------------------------------------------------------


def test_crop_clamp_x_y_out_of_bounds():
    """apply_crop с x/y за пределами изображения — clamp, не исключение."""
    arr = _bgr(50, 100)
    # x=90, y=40, w=50, h=30 — w/h выходят за правую/нижнюю границу
    result = apply_crop(arr, {"x": 90, "y": 40, "w": 50, "h": 30})
    # clamp: x=90, w=min(50,100-90)=10; y=40, h=min(30,50-40)=10
    assert result.shape == (10, 10, 3), f"Ожидается (10, 10, 3), получено {result.shape}"


def test_crop_clamp_negative_xy():
    """apply_crop с отрицательными x/y — clamp к 0."""
    arr = _bgr(50, 100)
    result = apply_crop(arr, {"x": -10, "y": -5, "w": 30, "h": 20})
    # clamp: x=0, y=0; w=min(30,100)=30, h=min(20,50)=20
    assert result.shape == (20, 30, 3), f"Ожидается (20, 30, 3), получено {result.shape}"


def test_crop_clamp_too_large_wh():
    """apply_crop с w/h больше размера изображения — clamp."""
    arr = _bgr(50, 100)
    result = apply_crop(arr, {"x": 0, "y": 0, "w": 9999, "h": 9999})
    # Clamp: w=100, h=50 — весь кадр
    assert result.shape == (50, 100, 3)


# ---------------------------------------------------------------------------
# Test 8: crop=None → passthrough (shape не меняется)
# ---------------------------------------------------------------------------


def test_crop_none_passthrough():
    """apply_crop(arr, None) возвращает arr без изменений shape."""
    arr = _bgr(100, 200)
    result = apply_crop(arr, None)
    assert result.shape == arr.shape
    # При None — возвращает тот же объект (оптимизация — не копия)
    assert result is arr


# ---------------------------------------------------------------------------
# Test 9: scale=10 (минимум) не падает
# ---------------------------------------------------------------------------


def test_scale_minimum_10():
    """apply_scale(10) не падает, размер уменьшается до 10%."""
    arr = _bgr(100, 200)
    result = apply_scale(arr, 10)
    expected_h = max(1, round(100 * 10 / 100))
    expected_w = max(1, round(200 * 10 / 100))
    assert result.shape[:2] == (expected_h, expected_w), (
        f"Ожидается ({expected_h}, {expected_w}), получено {result.shape[:2]}"
    )


def test_scale_below_minimum_clamped():
    """apply_scale(5) — меньше минимума, clamp до 10%."""
    arr = _bgr(100, 200)
    result_5 = apply_scale(arr, 5)
    result_10 = apply_scale(arr, 10)
    # Должны иметь одинаковый shape (clamp к 10)
    assert result_5.shape == result_10.shape, "scale=5 должен быть clamped до scale=10"


# ---------------------------------------------------------------------------
# Test 10: GRAY (2D) кадр проходит через полный pipeline
# ---------------------------------------------------------------------------


def test_gray_crop():
    """apply_crop работает с 2D GRAY-кадром."""
    arr = _gray(100, 200)
    result = apply_crop(arr, {"x": 0, "y": 0, "w": 60, "h": 40})
    assert result.shape == (40, 60), f"Ожидается (40, 60), получено {result.shape}"


def test_gray_scale():
    """apply_scale работает с 2D GRAY-кадром."""
    arr = _gray(100, 200)
    result = apply_scale(arr, 50)
    assert result.shape == (50, 100), f"Ожидается (50, 100), получено {result.shape}"


def test_gray_rotate_90():
    """apply_rotate(90) работает с 2D GRAY-кадром, меняет w/h."""
    arr = _gray(100, 200)
    result = apply_rotate(arr, 90)
    assert result.shape == (200, 100), f"Ожидается (200, 100), получено {result.shape}"


def test_gray_flip():
    """apply_flip работает с 2D GRAY-кадром."""
    arr = _gray(100, 200)
    result = apply_flip(arr, "vertical")
    assert result.shape == (100, 200), f"Ожидается (100, 200), получено {result.shape}"


def test_gray_full_pipeline():
    """run_pipeline работает с 2D GRAY-кадром."""
    arr = _gray(100, 200)
    params = {"crop": {"x": 0, "y": 0, "w": 100, "h": 50}, "scale": 200, "rotate": 90, "flip": "horizontal"}
    result = run_pipeline(arr, params)
    # crop: (50, 100), scale 200%: (100, 200), rotate 90: (200, 100)
    assert result.shape == (200, 100), f"Ожидается (200, 100), получено {result.shape}"


# ---------------------------------------------------------------------------
# Test 11: rotate 90 на неквадратном кадре — w/h меняются местами
# ---------------------------------------------------------------------------


def test_rotate_90_non_square():
    """apply_rotate(90) на неквадратном кадре (80x120): h=120, w=80 → h=80, w=120."""
    arr = np.zeros((80, 120, 3), dtype=np.uint8)  # h=80, w=120
    result = apply_rotate(arr, 90)
    # После rotate 90° CW: h=120, w=80
    assert result.shape == (120, 80, 3), f"Ожидается (120, 80, 3), получено {result.shape}"


def test_rotate_270_non_square():
    """apply_rotate(270) на неквадратном кадре (80x120) → h=80, w=120 становится h=120, w=80."""
    arr = np.zeros((80, 120, 3), dtype=np.uint8)
    result = apply_rotate(arr, 270)
    assert result.shape == (120, 80, 3), f"Ожидается (120, 80, 3), получено {result.shape}"
