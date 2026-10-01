# -*- coding: utf-8 -*-
"""Публичные типы слоёв фона `layer_render` (Task 1.1).

Два вида слоя стека фона (стек — снизу вверх):

- `SolidFill` — сплошная заливка кадра цветом RGB;
- `ScrollingTile` — тайл, который едет по оси X вместе с лентой и повторяется по ширине.

Оба — `frozen` dataclass: стек слоёв неизменяем после сборки. Цвет — сразу RGB (кадр
хранится в RGB; в BGR его переводит вызывающий).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SolidFill:
    """Сплошная заливка: `color_rgb` — три целых 0..255 в порядке R, G, B."""

    color_rgb: tuple[int, int, int]


@dataclass(frozen=True)
class ScrollingTile:
    """Тайл фона: `image` — uint8 `(H, W, 3)` RGB (непрозрачный) или `(H, W, 4)` RGBA (по альфе).

    Pre: `H >= 1`, `W >= 1`, uint8, 3 или 4 канала — иначе `ValueError` в конструкторе.
    Массив не копируется и не изменяется слоем.
    """

    image: np.ndarray

    def __post_init__(self) -> None:
        image = self.image
        if not isinstance(image, np.ndarray):
            raise ValueError(f"ScrollingTile.image: ожидался np.ndarray, получено {type(image)!r}")
        if image.dtype != np.uint8:
            raise ValueError(f"ScrollingTile.image: ожидался dtype=uint8, получено dtype={image.dtype}")
        if image.ndim != 3 or image.shape[2] not in (3, 4):
            raise ValueError(f"ScrollingTile.image: ожидалась форма (H, W, 3|4), получено shape={image.shape}")
        if image.shape[0] < 1 or image.shape[1] < 1:
            raise ValueError(f"ScrollingTile.image: высота и ширина должны быть >= 1, получено shape={image.shape}")
