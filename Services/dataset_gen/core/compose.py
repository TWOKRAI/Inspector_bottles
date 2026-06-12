"""Геометрия cut-and-paste: поворот с expand, обрезка по альфе, альфа-композиция.

Порядок применения в пайплайне кадра (фиксирован, см. engine.generate_sample):
rotate_expand → crop_to_alpha → fit_longest_side → composite.
Угол поворота — CCW (соглашение cv2.getRotationMatrix2D), он же ground truth.
"""

from __future__ import annotations

import math

import cv2
import numpy as np


def rotate_expand(sprite_rgba: np.ndarray, angle_deg: float) -> np.ndarray:
    """Повернуть RGBA-спрайт на angle_deg (CCW) с расширением холста.

    Холст расширяется так, чтобы повёрнутый объект поместился целиком;
    добавленные области полностью прозрачны (альфа сохраняется).

    Pre:
      - sprite_rgba: HxWx4 uint8
    Post:
      - выход RGBA uint8; контент не обрезан (границы холста ≥ повёрнутого bbox)
    """
    h, w = sprite_rgba.shape[:2]
    center = (w / 2.0, h / 2.0)
    m = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    new_w = int(math.ceil(h * sin + w * cos))
    new_h = int(math.ceil(h * cos + w * sin))
    m[0, 2] += new_w / 2.0 - center[0]
    m[1, 2] += new_h / 2.0 - center[1]
    return cv2.warpAffine(
        sprite_rgba,
        m,
        (new_w, new_h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )


def crop_to_alpha(sprite_rgba: np.ndarray) -> np.ndarray:
    """Обрезать спрайт по bbox непрозрачной области (alpha > 0).

    Убирает прозрачные «уголки» после поворота — они не должны попасть в кадр.

    Pre:
      - sprite_rgba: HxWx4 uint8, есть хотя бы один пиксель с alpha > 0
    Post:
      - крайние строки/столбцы результата содержат alpha > 0 (bbox плотный)
    """
    alpha = sprite_rgba[:, :, 3]
    ys, xs = np.nonzero(alpha)
    if ys.size == 0:
        raise ValueError("Спрайт полностью прозрачен — нечего обрезать")
    return sprite_rgba[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]


def fit_longest_side(sprite: np.ndarray, target_px: int) -> np.ndarray:
    """Масштабировать с сохранением пропорций: длинная сторона → target_px.

    Pre:
      - target_px ≥ 1
    Post:
      - max(выход.shape[:2]) == target_px (±1 от округления), пропорции сохранены
    """
    h, w = sprite.shape[:2]
    scale = target_px / max(h, w)
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
    return cv2.resize(sprite, (new_w, new_h), interpolation=interp)


def composite(
    background_rgb: np.ndarray,
    sprite_rgba: np.ndarray,
    center_xy: tuple[float, float],
) -> np.ndarray:
    """Альфа-композиция спрайта на фон, центр объекта в center_xy.

    Выступающая за края часть спрайта обрезается. Фон не модифицируется
    (возвращается копия).

    Pre:
      - background_rgb: HxWx3 uint8; sprite_rgba: hxwx4 uint8
    Post:
      - выход той же формы, что фон; вне зоны спрайта пиксели равны фону
    """
    bh, bw = background_rgb.shape[:2]
    sh, sw = sprite_rgba.shape[:2]
    cx, cy = center_xy
    x0 = int(round(cx - sw / 2.0))
    y0 = int(round(cy - sh / 2.0))

    bx0, by0 = max(0, x0), max(0, y0)
    bx1, by1 = min(bw, x0 + sw), min(bh, y0 + sh)
    out = background_rgb.copy()
    if bx0 >= bx1 or by0 >= by1:
        return out  # спрайт целиком за кадром

    region = sprite_rgba[by0 - y0 : by1 - y0, bx0 - x0 : bx1 - x0]
    alpha = region[:, :, 3:4].astype(np.float32) / 255.0
    fg = region[:, :, :3].astype(np.float32)
    bg = out[by0:by1, bx0:bx1].astype(np.float32)
    blended = fg * alpha + bg * (1.0 - alpha)
    out[by0:by1, bx0:bx1] = np.clip(blended + 0.5, 0, 255).astype(np.uint8)
    return out
