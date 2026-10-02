# -*- coding: utf-8 -*-
"""Квадратный вырез вокруг точки — ЕДИНСТВЕННАЯ реализация (Task 6.1).

Раньше жила в двух копиях: `center_crop._crop_square` (границы кадра по регистру) и вырез
в `ml_train.holdout_eval`. Здесь — одна функция с явным режимом у границы кадра `oob`.

Контракт — в README.md (Public API) и docs/maps/crop.md.
"""

from __future__ import annotations

from typing import Sequence

import cv2
import numpy as np

_OOB_MODES = ("drop", "pad", "clamp", "replicate")


def side_from_radius(radius: int | float, radius_scale: float, margin_px: int | float) -> int:
    """Сторона квадрата по радиусу: bbox круга (2·r·scale) плюс поля с обеих сторон, не меньше 2."""
    return max(2, int(round(2 * radius * float(radius_scale))) + 2 * int(margin_px))


def square_crop(
    frame: np.ndarray,
    cx: int,
    cy: int,
    side: int,
    oob: str,
    pad_value: Sequence[int] = (0, 0, 0),
) -> np.ndarray | None:
    """Квадрат `side`×`side` вокруг (cx, cy); левый верхний угол — `(cx - side//2, cy - side//2)`.

    Результат ВСЕГДА копия, не view кадра: кадры из SHM — read-only view, живой буфер переиспользуется.

    `oob` — что делать, когда квадрат выходит за кадр:
      * `drop`      — None (любой выход за границу);
      * `pad`       — холст `side`×`side`, залитый `pad_value`, перекрытие вклеено (нет перекрытия — чистый холст);
      * `clamp`     — вырез обрезан по кадру (меньше `side`); нет перекрытия — None;
      * `replicate` — недостающие поля достроены репликацией края кадра; нет перекрытия — ValueError
        (реплицировать нечего).
    Неизвестный `oob` — ValueError (проверяется до любой работы, в том числе для квадрата внутри кадра).
    """
    if oob not in _OOB_MODES:
        raise ValueError(f"unknown oob mode {oob!r}, expected one of {_OOB_MODES}")

    x0, y0 = cx - side // 2, cy - side // 2
    x1, y1 = x0 + side, y0 + side  # ширина/высота ровно = side
    h, w = frame.shape[:2]

    if x0 >= 0 and y0 >= 0 and x1 <= w and y1 <= h:
        return frame[y0:y1, x0:x1].copy()

    if oob == "drop":
        return None

    # Перекрытие квадрата с кадром (в координатах кадра).
    sx0, sy0 = max(0, x0), max(0, y0)
    sx1, sy1 = min(w, x1), min(h, y1)
    overlaps = sx1 > sx0 and sy1 > sy0

    if oob == "pad":
        canvas = _pad_canvas(side, frame, pad_value)
        if overlaps:
            dx0, dy0 = sx0 - x0, sy0 - y0
            canvas[dy0 : dy0 + (sy1 - sy0), dx0 : dx0 + (sx1 - sx0)] = frame[sy0:sy1, sx0:sx1]
        return canvas

    if oob == "clamp":
        if not overlaps:
            return None  # центр вне кадра целиком — выреза нет
        return frame[sy0:sy1, sx0:sx1].copy()

    # replicate
    if not overlaps:
        raise ValueError(f"replicate: square side={side} at center=({cx}, {cy}) does not overlap the {w}x{h} frame")
    # copyMakeBorder всегда отдаёт новый массив — view кадра наружу не уходит.
    return cv2.copyMakeBorder(frame[sy0:sy1, sx0:sx1], sy0 - y0, y1 - sy1, sx0 - x0, x1 - sx1, cv2.BORDER_REPLICATE)


def resize_square(crop: np.ndarray, out: int) -> np.ndarray:
    """Ресайз квадрата к `out`×`out` — единый размер для ML.

    `out <= 0` или вырез уже `out`×`out` — вход возвращается как есть (тот же объект). INTER_AREA при
    уменьшении (антиалиасинг), INTER_LINEAR иначе; режим выбирается по `crop.shape[0]`.
    """
    if out <= 0 or (crop.shape[0] == out and crop.shape[1] == out):
        return crop
    interp = cv2.INTER_AREA if crop.shape[0] > out else cv2.INTER_LINEAR
    return cv2.resize(crop, (out, out), interpolation=interp)


def _pad_canvas(side: int, frame: np.ndarray, pad_value: Sequence[int]) -> np.ndarray:
    """side×side холст, залитый pad_value (под формат/каналы кадра; лишние каналы — 0, 2D — первый компонент)."""
    color = [int(c) for c in pad_value]
    if frame.ndim == 3:
        c = frame.shape[2]
        canvas = np.zeros((side, side, c), dtype=frame.dtype)
        canvas[:] = (color + [0, 0, 0])[:c]
    else:  # grayscale
        canvas = np.full((side, side), color[0] if color else 0, dtype=frame.dtype)
    return canvas
