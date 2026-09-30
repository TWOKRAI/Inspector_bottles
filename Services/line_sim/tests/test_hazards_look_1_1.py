# -*- coding: utf-8 -*-
"""Hazard-тесты автора Task 1.1: что может сломаться в `find_period` (градиентный NCC).

Механизм: Sobel по X -> NCC двух сдвинутых копий для лагов `[_MIN_LAG - 1, W // 2 + 1]` ->
локальные максимумы -> наименьший в пределах 0.9 от лучшего. Опасные места:
- каналы: (H, W) и (H, W, 1) не проходят через cvtColor(BGR2GRAY) — там ошибка OpenCV;
- крайние размеры: соседи `c[k+1]` на верхней границе диапазона, узкое фото — IndexError;
- нулевой знаменатель: столбцово-постоянное изображение даёт gx == 0 -> деление на ноль / NaN;
- граница диапазона: период ровно W // 2 — последний допустимый лаг, нужен сосед W // 2 + 1;
- тип результата: numpy-int уедет в `range`/срезы/JSON неожиданно, нужен Python int.
Ожидаемые значения — литералы.
"""

from __future__ import annotations

import numpy as np

from Services.line_sim.tools.make_seamless_texture import find_period


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
    img = np.tile(np.linspace(0, 255, 200).astype(np.uint8)[None, :, None], (1, 1, 3))  # градиент есть
    flat_cols = np.tile(np.linspace(0, 255, 20).astype(np.uint8)[:, None, None], (1, 200, 3))  # gx == 0
    assert find_period(flat_cols) is None
    assert find_period(np.zeros((10, 100, 3), dtype=np.uint8)) is None
    assert img.shape == (1, 200, 3)  # гард: фикстура построена как задумано


def test_period_at_half_width_boundary_is_found():
    # W = 2P: лаг P == W // 2 — последний допустимый; сосед P + 1 должен считаться без IndexError
    img = _rows_pattern(100, 200)
    assert find_period(img) == 100


def test_period_just_inside_half_width_is_found():
    assert find_period(_rows_pattern(100, 202)) == 100


def test_result_is_python_int():
    got = find_period(_rows_pattern(50, 250))
    assert type(got) is int
