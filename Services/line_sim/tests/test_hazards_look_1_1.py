# -*- coding: utf-8 -*-
"""Hazard-тесты автора Task 1.1: что может сломаться в `find_period` (градиентный NCC).

Механизм: Sobel по X -> NCC двух сдвинутых копий для лагов `[_MIN_LAG - 1, W // 2 + 1]` ->
локальные максимумы -> наименьший в пределах 0.9 от лучшего. Опасные места:
- каналы: (H, W) и (H, W, 1) не проходят через cvtColor(BGR2GRAY) — там ошибка OpenCV;
- крайние размеры: соседи `c[k+1]` на верхней границе диапазона, узкое фото — IndexError;
- нулевой знаменатель: столбцово-постоянное изображение даёт gx == 0 -> деление на ноль / NaN;
- граница диапазона: период ровно W // 2 — последний допустимый лаг, нужен сосед W // 2 + 1;
- тип результата: numpy-int уедет в `range`/срезы/JSON неожиданно, нужен Python int.
Резерв `_period_multiple_crop` (кропы шириной k * период при провале `_best_crop`):
- не должен срабатывать, если `_best_crop` уже прошёл шов (иначе поведение 3_6 поменяется);
- опт-ин: без `force_period` не зовётся вовсе (H6 из 3_6 остаётся зеркалом), с флагом зовётся;
- k перебирается от большего к меньшему: при двух проходящих берётся больший (реже повтор фактуры);
- критерий шва не ослаблен: если ни один k не проходит — `None`, дальше зеркало.
Ожидаемые значения — литералы.
"""

from __future__ import annotations

import numpy as np

import cv2
from pathlib import Path

from Services.line_sim.tools.make_seamless_texture import (
    _period_multiple_crop,
    find_period,
    make_seamless_tile,
)

FIXTURE = Path(__file__).parent / "fixtures" / "belt_photo_full.png"


def _rows_pattern(period: int, width: int, rows: int = 16) -> np.ndarray:
    """Строки одинаковы: узкий пик яркости раз в `period` столбцов, фаза 10 (не у края)."""
    x = np.arange(width)
    col = np.where((x - 10) % period < 6, 220, 40).astype(np.uint8)
    return np.tile(col[None, :], (rows, 1))


def test_single_channel_2d_and_3d_work():
    gray2d = _rows_pattern(50, 250)
    assert find_period(gray2d) == 50
    assert find_period(gray2d[:, :, None]) == 50


def test_tiny_image_returns_none_without_error():
    for w in (1, 2, 5, 9):  # W < 2 * _MIN_LAG + 2 == 10
        assert find_period(np.random.default_rng(0).integers(0, 255, (8, w, 3), dtype=np.uint8)) is None


def test_column_constant_image_returns_none():
    flat_cols = np.tile(np.linspace(0, 255, 20).astype(np.uint8)[:, None, None], (1, 200, 3))  # gx == 0
    assert find_period(flat_cols) is None
    assert find_period(np.zeros((10, 100, 3), dtype=np.uint8)) is None


def test_period_at_half_width_boundary_is_found():
    # W = 2P: лаг P == W // 2 — последний допустимый; сосед P + 1 должен считаться без IndexError
    img = _rows_pattern(100, 200)
    assert find_period(img) == 100


def test_period_just_inside_half_width_is_found():
    assert find_period(_rows_pattern(100, 202)) == 100


def test_result_is_python_int():
    got = find_period(_rows_pattern(50, 250))
    assert type(got) is int


def _bgr(gray2d: np.ndarray) -> np.ndarray:
    return np.repeat(gray2d[:, :, None], 3, axis=2)


def test_fallback_not_used_when_best_crop_passes():
    img = _bgr(_rows_pattern(50, 300))
    res = make_seamless_tile(img, force_period=True)
    assert (res.method, res.period_px) == ("period", 50)
    assert res.note == ""  # у резерва note всегда непустой
    assert res.tile.shape[1] == 150
    assert np.array_equal(res.tile, img[:, :150])  # тайл _best_crop: start 0, ширина 150


def test_fallback_prefers_larger_k():
    res = _period_multiple_crop(_bgr(_rows_pattern(50, 125)), 50)  # проходят и k=2, и k=1 (шов 0.0)
    assert res is not None
    assert res.tile.shape[1] == 100
    assert res.note == "резерв: 2 период(а), старт 0"


def test_fallback_returns_none_when_no_k_passes_seam():
    ramp = np.tile(np.linspace(0, 255, 300).astype(np.uint8)[None, :, None], (8, 1, 3))  # шов ~170, внутри ~1
    assert _period_multiple_crop(ramp, 50) is None


def test_real_belt_photo_uses_one_period_fallback():
    img = cv2.imread(str(FIXTURE), cv2.IMREAD_COLOR)
    res = make_seamless_tile(img, force_period=True)
    assert (res.method, res.period_px, res.tile.shape) == ("period", 205, (484, 205, 3))
    assert res.note == "резерв: 1 период(а), старт 308"
    assert round(res.seam_diff, 2) == 8.58 and round(res.inner_diff, 2) == 17.79


def test_real_belt_photo_without_flag_is_mirror():
    img = cv2.imread(str(FIXTURE), cv2.IMREAD_COLOR)
    res = make_seamless_tile(img)
    assert (res.method, res.period_px) == ("mirror", None)
    assert res.note.startswith("период найден (205 px)")  # резерв не звался: note от отката, не «резерв:»


def test_h6_vignetted_sine_with_force_period_gives_period():
    """Задокументированный риск опт-ина: на H6 (виньетированная синусоида) флаг включает резерв."""
    x = np.arange(128)
    base = 128.0 + 100.0 * np.sin(2 * np.pi * x / 20)
    profile = np.clip(base * (1.0 - 0.8 * x / 127), 0, 255).astype(np.uint8)
    img = np.tile(profile[None, :, None], (6, 1, 3))
    assert make_seamless_tile(img).method == "mirror"
    res = make_seamless_tile(img, force_period=True)
    assert (res.method, res.period_px, res.tile.shape[1]) == ("period", 20, 100)
    assert res.note == "резерв: 5 период(а), старт 15"
