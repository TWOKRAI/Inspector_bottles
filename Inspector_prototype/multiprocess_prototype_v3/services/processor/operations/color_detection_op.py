"""Операция цветовой детекции — обёртка над ColorBlobDetector."""
from __future__ import annotations

from typing import List, Optional

import numpy as np

from ..detection import ColorBlobDetector
from .base import ChainContext

# Дефолтные значения синхронизированы с registers/constants.py:
#   DEFAULT_COLOR_LOWER, DEFAULT_COLOR_UPPER, DEFAULT_MIN_AREA, DEFAULT_MAX_AREA
# Прямой импорт из registers.constants невозможен на уровне services/:
# registers/__init__.py и registers/constants.py зависят от multiprocess_framework,
# который не всегда доступен в окружении (аналогично service.py, который
# получает detector снаружи, а не создаёт сам).
_DEFAULT_COLOR_LOWER = [0, 0, 150]
_DEFAULT_COLOR_UPPER = [100, 100, 255]
_DEFAULT_MIN_AREA = 500
_DEFAULT_MAX_AREA = 50000


class ColorDetectionOp:
    """Операция детекции цветных объектов.

    Реализует ProcessingOperation: принимает кадр, запускает ColorBlobDetector,
    сохраняет детекции/маску/контуры в атрибутах, возвращает mask_display.
    """

    def __init__(self) -> None:
        # Создаём детектор с дефолтными параметрами (синхронизированы с registers/constants.py)
        self._detector = ColorBlobDetector(
            color_lower=list(_DEFAULT_COLOR_LOWER),
            color_upper=list(_DEFAULT_COLOR_UPPER),
            min_area=_DEFAULT_MIN_AREA,
            max_area=_DEFAULT_MAX_AREA,
        )
        # Результаты последнего вызова execute
        self.last_detections: list = []
        self.last_mask: Optional[np.ndarray] = None
        self.last_contours: List[np.ndarray] = []

    def configure(self, params: dict) -> None:
        """Применить параметры к детектору.

        Поддерживаемые ключи: color_lower, color_upper, min_area, max_area.
        """
        color_lower = params.get("color_lower")
        color_upper = params.get("color_upper")
        if color_lower is not None or color_upper is not None:
            self._detector.apply_color_range(color_lower, color_upper)

        min_area = params.get("min_area")
        if min_area is not None:
            self._detector.set_min_area(int(min_area))

        max_area = params.get("max_area")
        if max_area is not None:
            self._detector.set_max_area(int(max_area))

    def execute(self, frame: np.ndarray, context: ChainContext) -> np.ndarray:
        """Запустить детекцию, вернуть mask_display.

        Результаты сохраняются в last_detections, last_mask, last_contours.
        """
        detections, mask_display, contours = self._detector.detect(frame)

        # Сохраняем результаты для внешнего доступа
        self.last_detections = detections
        self.last_mask = mask_display
        self.last_contours = contours

        return mask_display
