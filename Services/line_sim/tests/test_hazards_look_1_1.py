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
import pytest
from pathlib import Path

from Services.line_sim.tools.make_seamless_texture import (
    _period_multiple_crop,
    find_period,
    main,
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


def test_period_survives_brightness_ramp_gradient_not_brightness():
    """J1: NCC считается по градиенту, а не по яркости. Плавная рампа освещения 1.0 -> 0.4 вдоль X
    ломает яркостную корреляцию (на фикстуре она даёт ложный лаг 33), градиентную — почти нет."""
    img = cv2.imread(str(FIXTURE), cv2.IMREAD_COLOR)
    ramp = np.linspace(1.0, 0.4, img.shape[1])
    lit = np.clip(img.astype(np.float64) * ramp[None, :, None], 0, 255).astype(np.uint8)
    got = find_period(lit)
    assert got is not None and abs(got - 205) <= 1, f"find_period={got!r}, ждали 205 +-1"


def _best_gradient_ncc_peak(image: np.ndarray, min_lag: int = 4) -> float:
    """Лучший локальный максимум NCC градиента — независимый пересчёт для гарда пустого теста."""
    gx = cv2.Sobel(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32), cv2.CV_32F, 1, 0, ksize=3)
    width = image.shape[1]

    def ncc(k: int) -> float:
        a = gx[:, : width - k].ravel().astype(np.float64)
        b = gx[:, k:].ravel().astype(np.float64)
        a -= a.mean()
        b -= b.mean()
        return float(a @ b / np.sqrt((a @ a) * (b @ b)))

    c = {k: ncc(k) for k in range(min_lag - 1, width // 2 + 2)}
    return max(c[k] for k in range(min_lag, width // 2 + 1) if c[k - 1] < c[k] >= c[k + 1])


def test_noise_has_no_period_because_of_ncc_threshold():
    """J3: у белого шума локальные максимумы NCC есть, но слабые; порог `_NCC_MIN` их отсекает."""
    noise = np.random.default_rng(0).integers(0, 256, (60, 300, 3), dtype=np.uint8)
    best = _best_gradient_ncc_peak(noise)
    assert 0.0 < best < 0.2, f"гард: лучший максимум NCC на шуме {best:.3f} должен быть в (0, 0.2), иначе тест пустой"
    assert find_period(noise) is None


def test_cli_force_period_flag_reaches_make_seamless_tile(tmp_path, capsys):
    """Флаг `--force-period` в `main` реально доходит до `make_seamless_tile` (не подменён на False)."""
    out = tmp_path / "t.png"
    assert main([str(FIXTURE), "--out", str(out), "--force-period"]) == 0
    assert "method=period period_px=205" in capsys.readouterr().out
    assert cv2.imread(str(out), cv2.IMREAD_COLOR).shape == (484, 205, 3)

    out2 = tmp_path / "t2.png"
    assert main([str(FIXTURE), "--out", str(out2)]) == 0
    assert "method=mirror" in capsys.readouterr().out


@pytest.mark.parametrize("dtype", [np.uint8, np.uint16, np.int32, np.int64, np.float32, np.float64])
def test_find_period_accepts_any_numeric_dtype_bgr(dtype):
    """Pre обещает любой числовой dtype: cvtColor float64/int32/int64 не берёт — нужно привести до конвертации."""
    img = _bgr(_rows_pattern(50, 250)).astype(dtype)
    assert find_period(img) == 50


def test_note_says_fallback_was_tried_when_it_also_fails():
    """Период найден, но ни обычный кроп, ни резерв k·P шов не проходят — note об этом говорит."""
    x = np.arange(400)
    col = (np.linspace(0, 200, 400) + 8 * np.sin(2 * np.pi * x / 50)).clip(0, 255).astype(np.uint8)  # рампа рвёт шов
    img = _bgr(np.tile(col[None, :], (16, 1)))
    with_flag = make_seamless_tile(img, force_period=True)
    assert with_flag.method == "mirror"
    assert with_flag.note.startswith("период найден (50 px)")
    assert "резерв k·P тоже не прошёл шов" in with_flag.note
    assert "резерв" not in make_seamless_tile(img).note  # без флага резерв не пробовался
