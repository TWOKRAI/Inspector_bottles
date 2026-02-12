"""Преобразование в оттенки серого."""

import cv2
import numpy as np
from typing import Dict, Any, List
from ..base import BaseProcessor


class GrayscaleProcessor(BaseProcessor):
    def process(self, image: np.ndarray, params: Dict[str, Any]) -> np.ndarray:
        method = params.get("method", "luminance")
        if len(image.shape) == 2:
            return image.copy()
        if method == "luminance":
            gray = (0.299 * image[:, :, 2] + 0.587 * image[:, :, 1] + 0.114 * image[:, :, 0]).astype(np.uint8)
        else:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return gray

    def get_name(self) -> str:
        return "Оттенки серого"

    def get_params_schema(self) -> List[Dict]:
        return [
            {"key": "method", "type": "combo", "options": ["luminance", "default"], "default": "luminance"},
        ]
