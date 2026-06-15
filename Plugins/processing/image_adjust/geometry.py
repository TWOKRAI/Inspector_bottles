"""Коррекция изображения: яркость, контраст, насыщенность, гамма (чистая функция)."""

from __future__ import annotations

import cv2
import numpy as np


def apply_adjust(
    frame: np.ndarray,
    *,
    brightness: float = 0.0,
    contrast: float = 1.0,
    saturation: float = 1.0,
    gamma: float = 1.0,
) -> np.ndarray:
    """BGR-кадр → скорректированный BGR.

    brightness: аддитивное смещение (-255..255).
    contrast:   множитель вокруг серого 127.5 (1.0 = без изменений).
    saturation: множитель S в HSV (1.0 = без изменений).
    gamma:      гамма-коррекция (1.0 = без изменений; >1 светлее тени).
    """
    out = frame.astype(np.float32)
    # Контраст вокруг середины + яркость
    if contrast != 1.0 or brightness != 0.0:
        out = (out - 127.5) * float(contrast) + 127.5 + float(brightness)
    out = np.clip(out, 0, 255).astype(np.uint8)

    # Насыщенность через HSV
    if abs(saturation - 1.0) > 1e-3:
        hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[..., 1] = np.clip(hsv[..., 1] * float(saturation), 0, 255)
        out = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    # Гамма через LUT
    if abs(gamma - 1.0) > 1e-3:
        inv = 1.0 / max(float(gamma), 1e-3)
        lut = (np.power(np.linspace(0.0, 1.0, 256), inv) * 255.0).astype(np.uint8)
        out = cv2.LUT(out, lut)

    return out
