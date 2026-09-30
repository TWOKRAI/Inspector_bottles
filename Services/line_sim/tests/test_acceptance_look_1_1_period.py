# -*- coding: utf-8 -*-
"""Независимые acceptance-тесты Task 1.1 (line-sim-belt-look): период цепи на реальном фото.

Источник контракта: раздел "### Task 1.1" плана `plans/line-sim-belt-look/plan.md`
(критерии приёмки, 6 чекбоксов). Написаны ДО реализации, в git worktree на коммите
1a2bba9b (реализации правки нет по конструкции).

Читалось: раздел плана, публичные сигнатуры и docstring `find_period`,
`make_seamless_tile`, `SeamlessResult` (через `inspect`), `test_acceptance_3_6.py`
(стиль). НЕ читалось: тело `make_seamless_texture.py`, `_impl`, любые другие ветки и
worktree.

Причина дефекта (репродукция лида): на `fixtures/belt_photo_full.png` (598x484 BGR, цепь,
истинный шаг ~204 px) `find_period` берёт ПЕРВЫЙ локальный максимум автокорреляции с
ac/ac0 >= 0.5 — ложный лаг 43 — и инструмент уходит в `method == "mirror"`.

Ожидаемые значения — литералы из критериев (202..206, 484, P±1), не пересчитываются из
кода под тестом. Синтетика строится так, чтобы ложный короткий максимум ДЕЙСТВИТЕЛЬНО
существовал: тест сам считает нормированную автокорреляцию numpy и утверждает его
наличие (иначе тест вакуумен).
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from Services.line_sim.tools.make_seamless_texture import find_period, make_seamless_tile

FIXTURE = Path(__file__).parent / "fixtures" / "belt_photo_full.png"
ROWS = 48  # высота синтетических кадров; значения не важны, важна форма профиля по X


# ── помощники (независимая от кода под тестом математика) ─────────────────────────────


def _profile(period: int, width: int, amps: tuple[float, ...], spacing: int, sigma: float = 3.0):
    """Периодический профиль: в каждом периоде цепочка узких гауссовых пиков с шагом `spacing`.

    Фаза подобрана так, чтобы края окна попадали в промежутки между пиками: иначе пик,
    обрезанный краем, сдвигает максимум АКФ конечного окна (замер: P=100, W=4P -> лаг 98) и
    тест требовал бы от кода борьбы с краевым эффектом, которого в критерии нет.
    """
    x = np.arange(width, dtype=float)
    p = np.zeros(width)
    phase = (period - (len(amps) - 1) * spacing) / 2.0
    for k in range(-1, width // period + 2):
        for i, a in enumerate(amps):
            p += a * np.exp(-0.5 * ((x - (phase + k * period + i * spacing)) / sigma) ** 2)
    return p


def _to_image(profile: np.ndarray) -> np.ndarray:
    """Профиль -> uint8 (ROWS, W, 3): строки одинаковы, шкала 40..~220 (квантование пренебрежимо)."""
    col = 40.0 + 180.0 * profile / profile.max()
    img = np.tile(col.astype(np.uint8)[None, :, None], (ROWS, 1, 3))
    return img


def _norm_ac(image: np.ndarray) -> np.ndarray:
    """Нормированная (ac[0] == 1) автокорреляция центрированного профиля столбцов."""
    prof = image.astype(float).mean(axis=(0, 2))
    c = prof - prof.mean()
    ac = np.correlate(c, c, "full")[len(c) - 1 :]
    return ac / ac[0]


def _local_maxima(ac: np.ndarray, kmin: int, kmax: int) -> list[int]:
    return [k for k in range(kmin, kmax + 1) if ac[k - 1] < ac[k] >= ac[k + 1]]


# ── реальное фото ─────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def real_result():
    img = cv2.imread(str(FIXTURE), cv2.IMREAD_COLOR)
    assert img is not None, f"фикстура не читается: {FIXTURE}"
    assert img.shape == (484, 598, 3), f"неожиданная форма фикстуры: {img.shape}"
    return make_seamless_tile(img)


def test_real_belt_photo_gives_period_tile(real_result):
    """Критерий 1: method == 'period', period_px в [202, 206], высота тайла 484."""
    r = real_result
    assert r.method == "period", f"method={r.method!r} period_px={r.period_px!r} (ждали 'period'); note={r.note!r}"
    assert r.period_px is not None and 202 <= r.period_px <= 206, (
        f"period_px={r.period_px!r} вне [202, 206]; method={r.method!r}"
    )
    assert r.tile.shape[0] == 484, f"высота тайла {r.tile.shape[0]}, ждали 484"


def test_real_belt_photo_tile_seam_not_worse_than_inner(real_result):
    """Критерий 2: шов не хуже внутренней разницы (критерий инструмента не ослаблен)."""
    r = real_result
    # без этой проверки тест вакуумен: у 'mirror' шов ~0 и критерий выполняется тривиально
    assert r.method == "period", f"method={r.method!r}: критерий шва осмыслен только для тайла по периоду"
    assert r.seam_diff <= r.inner_diff, (
        f"seam_diff={r.seam_diff:.2f} > inner_diff={r.inner_diff:.2f}; method={r.method!r} period_px={r.period_px!r}"
    )


# ── синтетика: ложный короткий максимум ───────────────────────────────────────────────


@pytest.mark.parametrize(
    ("period", "width", "amps", "spacing", "spurious_lag"),
    [
        (120, 720, (1.0, 1.0, 0.5), 30, 30),  # ложный лаг 30 = P/4
        (160, 800, (1.0, 1.0, 0.4), 50, 50),  # ложный лаг 50 ~ P/3
    ],
)
def test_spurious_short_maximum_does_not_win(period, width, amps, spacing, spurious_lag):
    """Критерий 3: сильный побочный максимум на коротком лаге не должен побеждать период P."""
    img = _to_image(_profile(period, width, amps, spacing))
    assert width >= 4 * period

    # Гард против вакуумного теста: ложный максимум существует и подходит под старое правило.
    ac = _norm_ac(img)
    maxima = _local_maxima(ac, 4, width // 2)
    assert spurious_lag in maxima, f"нет локального максимума на лаге {spurious_lag}: {maxima}"
    assert ac[spurious_lag] >= 0.5, f"ac/ac0 на лаге {spurious_lag} = {ac[spurious_lag]:.3f} < 0.5"
    assert spurious_lag < period - 5
    assert ac[period] > ac[spurious_lag], "истинный период должен быть сильнее ложного"
    true_lag = 4 + int(np.argmax(ac[4 : width // 2 + 1]))
    assert abs(true_lag - period) <= 1, f"фикстура: глобальный максимум АКФ на {true_lag}, не {period}"

    got = find_period(img)
    assert got is not None and abs(got - period) <= 1, (
        f"find_period={got!r}, ждали {period}±1 (ложный лаг {spurious_lag}, ac/ac0={ac[spurious_lag]:.2f})"
    )


# ── синтетика: чистый период, не 2P ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("period", "width"),
    [(100, 400), (100, 500), (64, 512)],  # W = 4P, 5P, 8P
)
def test_clean_period_is_p_not_2p(period, width):
    """Критерий 4: чистый период P при W >= 4P -> P, гармоника 2P не выигрывает."""
    img = _to_image(_profile(period, width, (1.0,), 0, sigma=8.0))
    assert width >= 4 * period
    ac = _norm_ac(img)
    assert period in _local_maxima(ac, 4, width // 2), "фикстура: нет локального максимума АКФ на P"
    got = find_period(img)
    assert got is not None and abs(got - period) <= 1, (
        f"find_period={got!r}, ждали {period}±1 (W={width}, 2P={2 * period})"
    )


# ── плоское изображение ───────────────────────────────────────────────────────────────


def test_flat_image_has_no_period():
    """Критерий 5: у плоского изображения периода нет."""
    flat = np.full((64, 300, 3), 128, dtype=np.uint8)
    got = find_period(flat)
    assert got is None, f"find_period(flat)={got!r}, ждали None"


def test_flat_image_falls_back_to_mirror():
    """Критерий 5: плоское изображение -> method 'mirror', period_px None, высота сохранена."""
    flat = np.full((64, 300, 3), 128, dtype=np.uint8)
    r = make_seamless_tile(flat)
    assert r.method == "mirror", f"method={r.method!r} period_px={r.period_px!r}"
    assert r.period_px is None, f"period_px={r.period_px!r}"
    assert r.tile.shape[0] == 64, f"высота тайла {r.tile.shape[0]}, ждали 64"
