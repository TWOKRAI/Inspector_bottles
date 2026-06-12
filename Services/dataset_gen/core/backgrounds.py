"""Процедурные фоны: несколько типов текстур, имитирующих сцену конвейера.

Используются, когда `backgrounds_dir` не задан. Не заменяют реальные фото
полностью, но дают разнообразие сильно богаче «градиент + шум»: модель не
переобучается на один тип подложки. Для боевого датасета всё равно лучше
подложить фото реальной сцены — процедурка это «бесплатный» baseline.

Каждый генератор детерминирован от rng и возвращает RGB uint8 (H, W, 3).
"""

from __future__ import annotations

from typing import Callable

import cv2
import numpy as np


def _low_freq(rng: np.random.Generator, size_hw: tuple[int, int], cells: int) -> np.ndarray:
    """Низкочастотное поле [0..1] через апсемплинг мелкой случайной решётки."""
    h, w = size_hw
    grid = rng.random((cells, cells)).astype(np.float32)
    field = cv2.resize(grid, (w, h), interpolation=cv2.INTER_CUBIC)
    lo, hi = float(field.min()), float(field.max())
    return (field - lo) / max(hi - lo, 1e-6)


def gradient_bg(rng: np.random.Generator, size_hw: tuple[int, int]) -> np.ndarray:
    """Базовый цвет + плавный низкочастотный градиент + лёгкий шум."""
    h, w = size_hw
    base = rng.uniform(50.0, 200.0, size=3).astype(np.float32)
    low = rng.normal(0.0, 1.0, size=(4, 4, 3)).astype(np.float32)
    gradient = cv2.resize(low, (w, h), interpolation=cv2.INTER_CUBIC) * rng.uniform(8.0, 35.0)
    noise = rng.normal(0.0, 3.0, size=(h, w, 3)).astype(np.float32)
    return np.clip(base[None, None, :] + gradient + noise, 0, 255).astype(np.uint8)


def brushed_metal_bg(rng: np.random.Generator, size_hw: tuple[int, int]) -> np.ndarray:
    """Шлифованный металл: сильно анизотропный (вытянутый) шум + блик-полоса."""
    h, w = size_hw
    angle = float(rng.choice([0.0, 90.0]))
    streaks = rng.normal(0.0, 1.0, size=(h, w)).astype(np.float32)
    # вытягиваем шум вдоль направления → штрихи шлифовки
    ksize = max(3, (max(h, w) // 6) | 1)
    streaks = cv2.GaussianBlur(streaks, (ksize, 1) if angle == 0.0 else (1, ksize), 0)
    streaks = (streaks - streaks.min()) / max(streaks.max() - streaks.min(), 1e-6)
    base = rng.uniform(90.0, 170.0)
    gray = base + (streaks - 0.5) * rng.uniform(30.0, 70.0)
    gray += (_low_freq(rng, size_hw, 3) - 0.5) * 25.0  # неравномерность освещения
    tint = rng.uniform(-8.0, 8.0, size=3).astype(np.float32)
    return np.clip(gray[:, :, None] + tint[None, None, :], 0, 255).astype(np.uint8)


def conveyor_belt_bg(rng: np.random.Generator, size_hw: tuple[int, int]) -> np.ndarray:
    """Резиновая/тканевая лента: тёмная основа + поперечные стыки-планки."""
    h, w = size_hw
    base = rng.uniform(35.0, 90.0)
    field = base + (_low_freq(rng, size_hw, 5) - 0.5) * 20.0
    # поперечные планки ленты со случайным шагом и фазой
    period = int(rng.uniform(h * 0.3, h * 0.8))
    phase = int(rng.uniform(0, period))
    yy = np.arange(h)
    seam = ((yy + phase) % period < max(2, period // 12)).astype(np.float32)
    field -= seam[:, None] * rng.uniform(15.0, 35.0)
    field += rng.normal(0.0, 4.0, size=(h, w))  # зернистость
    tint = rng.uniform(-6.0, 6.0, size=3).astype(np.float32)
    return np.clip(field[:, :, None] + tint[None, None, :], 0, 255).astype(np.uint8)


def speckled_bg(rng: np.random.Generator, size_hw: tuple[int, int]) -> np.ndarray:
    """Пятнистая поверхность: основа + случайные мягкие пятна (загрязнение/фактура)."""
    h, w = size_hw
    base = rng.uniform(70.0, 180.0, size=3).astype(np.float32)
    field = np.broadcast_to(base, (h, w, 3)).astype(np.float32).copy()
    for _ in range(int(rng.integers(6, 16))):
        cx, cy = rng.uniform(0, w), rng.uniform(0, h)
        radius = rng.uniform(min(h, w) * 0.05, min(h, w) * 0.25)
        amp = rng.uniform(-40.0, 40.0)
        yy, xx = np.ogrid[:h, :w]
        falloff = np.clip(1.0 - np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / radius, 0, 1) ** 2
        field += (amp * falloff)[:, :, None]
    field += rng.normal(0.0, 3.0, size=(h, w, 3))
    return np.clip(field, 0, 255).astype(np.uint8)


_GENERATORS: tuple[Callable[[np.random.Generator, tuple[int, int]], np.ndarray], ...] = (
    gradient_bg,
    brushed_metal_bg,
    conveyor_belt_bg,
    speckled_bg,
)


def procedural_background(rng: np.random.Generator, size_hw: tuple[int, int]) -> np.ndarray:
    """Случайный процедурный фон одного из типов (RGB uint8, форма size_hw).

    Pre:
      - size_hw — (H, W), оба ≥ 1
    Post:
      - shape == (*size_hw, 3), dtype uint8
    """
    generator = _GENERATORS[int(rng.integers(len(_GENERATORS)))]
    return generator(rng, size_hw)
