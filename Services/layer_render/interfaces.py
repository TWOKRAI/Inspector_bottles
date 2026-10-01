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
    """Сплошная заливка: `color_rgb` — три целых 0..255 в порядке R, G, B.

    Pre: три целых 0..255 (bool/float/str не принимаются) — иначе `ValueError`. Сохраняется кортежем.
    """

    color_rgb: tuple[int, int, int]

    def __post_init__(self) -> None:
        color = self.color_rgb
        if not isinstance(color, (list, tuple)) or len(color) != 3:
            raise ValueError(f"SolidFill.color_rgb: ожидались три целых [R, G, B]: {color!r}")
        for channel in color:
            # bool — подкласс int: True/False как канал цвета отвергаются явно.
            if isinstance(channel, bool) or not isinstance(channel, int):
                raise ValueError(f"SolidFill.color_rgb: каналы должны быть целыми числами: {color!r}")
            if not 0 <= channel <= 255:
                raise ValueError(f"SolidFill.color_rgb: каналы должны лежать в 0..255: {color!r}")
        object.__setattr__(self, "color_rgb", tuple(color))


@dataclass(frozen=True, eq=False)
class ScrollingTile:
    """Тайл фона: `image` — uint8 `(H, W, 3)` RGB (непрозрачный) или `(H, W, 4)` RGBA (по альфе).

    Pre: `H >= 1`, `W >= 1`, uint8, 3 или 4 канала — иначе `ValueError` в конструкторе.
    Слой хранит собственную копию массива, только для чтения: правка исходника после создания слоя на кадр не
    влияет. `eq=False` — сравнение и хеш по идентичности (поле-ndarray ломает поэлементное `==`).
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
        frozen_copy = np.array(image, copy=True)
        frozen_copy.flags.writeable = False
        object.__setattr__(self, "image", frozen_copy)
