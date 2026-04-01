"""Цветовая детекция пятен (BGR). Без зависимости от ProcessModule."""

from __future__ import annotations

from typing import List, Tuple

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None


class ColorBlobDetector:
    """Состояние и детекция по диапазону BGR и площади."""

    def __init__(
        self,
        color_lower,
        color_upper,
        min_area: int,
        max_area: int,
    ) -> None:
        self._color_lower = np.asarray(color_lower, dtype=np.uint8)
        self._color_upper = np.asarray(color_upper, dtype=np.uint8)
        self._min_area = int(min_area)
        self._max_area = int(max_area)

    @property
    def color_lower(self) -> np.ndarray:
        return self._color_lower

    @property
    def color_upper(self) -> np.ndarray:
        return self._color_upper

    @property
    def min_area(self) -> int:
        return self._min_area

    @property
    def max_area(self) -> int:
        return self._max_area

    def apply_color_range(self, lower=None, upper=None) -> None:
        if lower is not None and len(lower) >= 3:
            self._color_lower = np.array(
                [max(0, min(255, int(lower[i]))) for i in range(3)],
                dtype=np.uint8,
            )
        if upper is not None and len(upper) >= 3:
            self._color_upper = np.array(
                [max(0, min(255, int(upper[i]))) for i in range(3)],
                dtype=np.uint8,
            )

    def set_min_area(self, value: int) -> None:
        self._min_area = max(10, min(10000, int(value)))

    def set_max_area(self, value: int) -> None:
        from multiprocess_prototype_v2.app_registers.processing_tab.boot import (
            processor_max_area_clamp,
        )

        upper = processor_max_area_clamp()
        self._max_area = max(0, min(upper, int(value)))

    def detect(self, frame: np.ndarray) -> Tuple[list, np.ndarray, List[np.ndarray]]:
        mask_binary = np.all(
            (frame >= self._color_lower) & (frame <= self._color_upper),
            axis=2,
        ).astype(np.uint8) * 255

        detections = []
        ys, xs = np.where(mask_binary > 0)
        if len(ys) >= self._min_area:
            area = int(len(ys))
            if self._max_area <= 0 or area <= self._max_area:
                x_min, x_max = int(xs.min()), int(xs.max())
                y_min, y_max = int(ys.min()), int(ys.max())
                cx = (x_min + x_max) // 2
                cy = (y_min + y_max) // 2
                detections.append(
                    {
                        "bbox": [x_min, y_min, x_max, y_max],
                        "center": [cx, cy],
                        "area": area,
                    }
                )

        contours: List[np.ndarray] = []
        if cv2 is not None:
            cnts, _ = cv2.findContours(
                mask_binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            contours = [c.astype(np.int32) for c in cnts]

        mask_display = np.stack([mask_binary] * 3, axis=-1)
        return detections, mask_display, contours
