# -*- coding: utf-8 -*-
"""
Конвертер сырых кадров Hikvision в BGR.

Поддерживает Bayer RG8, Grayscale, RGBA, RGB → BGR.
"""

from __future__ import annotations

import cv2
import numpy as np

from Services.hikvision_camera.sdk.constants import PixelType


class FrameConverter:
    """Конвертер сырых кадров Hikvision в BGR (3 канала)."""

    # Маппинг PixelType → cv2 код конвертации
    _BAYER_CONVERSIONS: dict[int, int] = {
        PixelType.BAYER_RG8: cv2.COLOR_BayerRG2BGR,
        PixelType.BAYER_GR8: cv2.COLOR_BayerGR2BGR,
        PixelType.BAYER_GB8: cv2.COLOR_BayerGB2BGR,
        PixelType.BAYER_BG8: cv2.COLOR_BayerBG2BGR,
    }

    @staticmethod
    def to_bgr(frame: np.ndarray, pixel_type: int) -> np.ndarray | None:
        """Конвертировать сырой кадр в BGR (3 канала).

        Поддерживаемые форматы:
        - Bayer RG8 / GR8 / GB8 / BG8 → BGR
        - Grayscale (Mono8) → BGR
        - RGBA → BGR
        - RGB → BGR

        Parameters
        ----------
        frame : np.ndarray
            Сырой кадр из capture_frame().
        pixel_type : int
            Тип пикселя из SDK (значение PixelType enum).

        Returns
        -------
        np.ndarray | None
            Кадр в формате BGR (3 канала) или None если формат
            не поддерживается.
        """
        if frame is None or frame.size == 0:
            return None

        # Bayer-паттерны
        bayer_code = FrameConverter._BAYER_CONVERSIONS.get(pixel_type)
        if bayer_code is not None:
            return cv2.cvtColor(frame, bayer_code)

        # Grayscale (Mono8)
        if pixel_type == PixelType.MONO8:
            return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

        # RGBA (4 канала → 3 канала BGR)
        if pixel_type == PixelType.RGBA8 and frame.ndim == 3 and frame.shape[2] == 4:
            return cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)

        # RGB (3 канала → BGR)
        if pixel_type == PixelType.RGB8 and frame.ndim == 3 and frame.shape[2] == 3:
            return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        # Если кадр уже 3-канальный — возвращаем как есть (возможно BGR)
        if frame.ndim == 3 and frame.shape[2] == 3:
            return frame

        return None

    @staticmethod
    def resize(frame: np.ndarray, width: int, height: int, mode: str = "letterbox") -> np.ndarray:
        """Ресайз кадра до (width, height). Если размер совпадает — no-op.

        Режимы (`mode`):
        - ``"letterbox"`` (по умолчанию, безопасный): сохраняет аспект кадра,
          вписывает в целевой прямоугольник и добивает чёрными полями. Геометрия
          объектов НЕ искажается — критично для CV/ML (круги остаются кругами).
        - ``"stretch"``: анаморфный ресайз без сохранения аспекта. При несовпадении
          аспекта сенсора и цели искажает геометрию (круги → эллипсы) — находка
          аудита H2. Оставлен как явная опция для случаев, где заливка важнее формы.

        Любое неизвестное значение `mode` трактуется как ``"letterbox"`` (fail-safe).

        Parameters
        ----------
        frame : np.ndarray
            Входной кадр (2D grayscale или 3D BGR).
        width : int
            Целевая ширина.
        height : int
            Целевая высота.
        mode : str
            ``"letterbox"`` | ``"stretch"``.

        Returns
        -------
        np.ndarray
            Кадр с размером ровно (height, width[, C]).
        """
        h, w = frame.shape[:2]
        if w == width and h == height:
            return frame
        if mode == "stretch":
            return cv2.resize(frame, (width, height), interpolation=cv2.INTER_LINEAR)

        # letterbox: вписываем с сохранением аспекта + чёрные поля
        scale = min(width / w, height / h)
        new_w = max(1, round(w * scale))
        new_h = max(1, round(h * scale))
        resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

        if frame.ndim == 3:
            canvas = np.zeros((height, width, frame.shape[2]), dtype=frame.dtype)
        else:
            canvas = np.zeros((height, width), dtype=frame.dtype)
        x0 = (width - new_w) // 2
        y0 = (height - new_h) // 2
        canvas[y0 : y0 + new_h, x0 : x0 + new_w] = resized
        return canvas
