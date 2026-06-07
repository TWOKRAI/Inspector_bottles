# -*- coding: utf-8 -*-
"""render_pipeline.py — конвейер трансформаций кадра для окна превью.

Чистые функции (без Qt, без side-effects). Порядок применения:
    crop → scale → rotate → flip

Функция ``run_pipeline`` запускает весь конвейер.
Результат передаётся в ``_numpy_to_qimage``, после чего Qt-слой
применяет fit-режим при отображении в QLabel.

Инварианты:
    - Входной массив НЕ мутируется — каждая функция возвращает НОВЫЙ ndarray
      (либо исходный без изменений, если трансформация — no-op).
    - Тип вывода — numpy.ndarray.
    - GRAY-кадры (ndim=2) проходят через crop/scale как есть;
      rotate/flip работают корректно для 2D array.

Refs: plans/displays-in-recipe/plan.md, Task 4.1
      docs/direction/displays-in-recipe.md §7, §11
"""

from __future__ import annotations

import logging
from typing import Any

import cv2
import numpy as np

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# apply_crop
# ---------------------------------------------------------------------------


def apply_crop(arr: np.ndarray, crop: dict[str, int] | None) -> np.ndarray:
    """Обрезать кадр по прямоугольнику в пикселях SHM-кадра.

    Args:
        arr:  numpy ndarray формы (H, W) или (H, W, C). НЕ мутируется.
        crop: dict с ключами ``x``, ``y``, ``w``, ``h`` в пикселях, или None.

    Returns:
        Новый ndarray — срез кадра. При crop=None возвращает arr без изменений.

    Граничные условия:
        - crop=None → возвращает arr без копирования.
        - Значения x/y/w/h клампируются к допустимым границам изображения.
        - Нулевая или отрицательная область после clamp → возвращает arr без изменений.
    """
    if crop is None:
        return arr

    img_h, img_w = arr.shape[:2]

    # Clamp координат к границам изображения
    x = max(0, int(crop.get("x", 0)))
    y = max(0, int(crop.get("y", 0)))
    w = int(crop.get("w", img_w))
    h = int(crop.get("h", img_h))

    # Ограничиваем правый/нижний край
    x = min(x, img_w - 1)
    y = min(y, img_h - 1)
    w = min(w, img_w - x)
    h = min(h, img_h - y)

    if w <= 0 or h <= 0:
        _logger.warning(
            "apply_crop: пустая область после clamp (x=%d y=%d w=%d h=%d), crop пропущен",
            x,
            y,
            w,
            h,
        )
        return arr

    # Возвращаем копию — срез numpy без copy() является view (мутирует оригинал при записи)
    return arr[y : y + h, x : x + w].copy()


# ---------------------------------------------------------------------------
# apply_scale
# ---------------------------------------------------------------------------


def apply_scale(arr: np.ndarray, scale_pct: int) -> np.ndarray:
    """Масштабировать кадр на заданный процент.

    Args:
        arr:       numpy ndarray формы (H, W) или (H, W, C). НЕ мутируется.
        scale_pct: масштаб в процентах. Допустимый диапазон: [10, 1000].
                   100 = без изменений. Значения вне диапазона клампируются.

    Returns:
        Новый ndarray — масштабированный кадр.
        При scale_pct=100 возвращает копию кадра.
    """
    # Clamp к допустимому диапазону согласно спеке §11 (#2)
    scale_pct = max(10, min(1000, int(scale_pct)))

    if scale_pct == 100:
        return arr.copy()

    h, w = arr.shape[:2]
    new_w = max(1, int(round(w * scale_pct / 100)))
    new_h = max(1, int(round(h * scale_pct / 100)))

    # INTER_AREA для уменьшения (лучшее качество), INTER_LINEAR для увеличения
    interpolation = cv2.INTER_AREA if scale_pct < 100 else cv2.INTER_LINEAR
    return cv2.resize(arr, (new_w, new_h), interpolation=interpolation)


# ---------------------------------------------------------------------------
# apply_rotate
# ---------------------------------------------------------------------------

# Маппинг градусов → флаг cv2.rotate
_ROTATE_MAP: dict[int, int] = {
    90: cv2.ROTATE_90_CLOCKWISE,
    180: cv2.ROTATE_180,
    270: cv2.ROTATE_90_COUNTERCLOCKWISE,
}


def apply_rotate(arr: np.ndarray, deg: int) -> np.ndarray:
    """Повернуть кадр на 0 / 90 / 180 / 270 градусов по часовой стрелке.

    При 90 и 270 градусах ширина и высота кадра меняются местами.

    Args:
        arr: numpy ndarray формы (H, W) или (H, W, C). НЕ мутируется.
        deg: угол поворота — 0, 90, 180 или 270. Остальные значения → no-op + warning.

    Returns:
        Новый ndarray — повёрнутый кадр. При deg=0 — копия исходного.
    """
    if deg == 0:
        return arr.copy()

    rotate_code = _ROTATE_MAP.get(int(deg))
    if rotate_code is None:
        _logger.warning(
            "apply_rotate: неподдерживаемый угол %s (допустимо 0/90/180/270), rotate пропущен",
            deg,
        )
        return arr.copy()

    return cv2.rotate(arr, rotate_code)


# ---------------------------------------------------------------------------
# apply_flip
# ---------------------------------------------------------------------------

# Маппинг режима → flipCode для cv2.flip
# cv2.flip flipCode: 1=горизонтально, 0=вертикально, -1=оба
_FLIP_MAP: dict[str, int] = {
    "horizontal": 1,
    "vertical": 0,
    "both": -1,
}


def apply_flip(arr: np.ndarray, mode: str) -> np.ndarray:
    """Отразить кадр по заданной оси.

    Args:
        arr:  numpy ndarray формы (H, W) или (H, W, C). НЕ мутируется.
        mode: режим отражения:
              ``"none"``       — без изменений;
              ``"horizontal"`` — зеркало по вертикальной оси (flipCode=1);
              ``"vertical"``   — зеркало по горизонтальной оси (flipCode=0);
              ``"both"``       — оба отражения (flipCode=-1).

    Returns:
        Новый ndarray — отражённый кадр. При mode="none" — копия исходного.
    """
    if mode == "none" or mode is None:
        return arr.copy()

    flip_code = _FLIP_MAP.get(str(mode))
    if flip_code is None:
        _logger.warning(
            "apply_flip: неизвестный режим '%s' (допустимо none/horizontal/vertical/both), flip пропущен",
            mode,
        )
        return arr.copy()

    return cv2.flip(arr, flip_code)


# ---------------------------------------------------------------------------
# run_pipeline
# ---------------------------------------------------------------------------


def run_pipeline(arr: np.ndarray, params: dict[str, Any] | None) -> np.ndarray:
    """Применить полный конвейер трансформаций в порядке crop→scale→rotate→flip.

    Входной массив НЕ мутируется — возвращается новый ndarray.

    Порядок согласно спеке §7 / §11 (#3):
        1. crop  — обрезка по пикселям SHM-кадра
        2. scale — масштабирование в %
        3. rotate — поворот 0/90/180/270°
        4. flip  — отражение

    Fit-режим НЕ применяется здесь — он реализован на Qt-уровне в PreviewWindow
    при установке QPixmap в QLabel (KeepAspectRatio / IgnoreAspectRatio / etc.).

    Args:
        arr:    Исходный numpy ndarray (SHM-кадр или синтетический). НЕ мутируется.
        params: dict с ключами:
                  ``"crop"``   — dict {x, y, w, h} или None
                  ``"scale"``  — int (%), по умолчанию 100
                  ``"rotate"`` — int (deg), по умолчанию 0
                  ``"flip"``   — str, по умолчанию "none"
                При params=None — используются дефолты (no-op pipeline).

    Returns:
        Новый ndarray после применения всех трансформаций.
    """
    if params is None:
        params = {}

    crop = params.get("crop", None)
    scale = int(params.get("scale", 100))
    rotate = int(params.get("rotate", 0))
    flip = str(params.get("flip", "none"))

    # Short-circuit: все параметры дефолтные → конвейер no-op. Возвращаем
    # исходный массив без 3 лишних copy (hot path 22fps, экономит ~1.6мс/кадр).
    # Контракт немутируемости сохраняется: вызывающий код кадр не меняет.
    if crop is None and scale == 100 and rotate == 0 and flip == "none":
        return arr

    result = apply_crop(arr, crop)
    result = apply_scale(result, scale)
    result = apply_rotate(result, rotate)
    result = apply_flip(result, flip)

    return result
