"""Размытие."""

import cv2
import numpy as np
from typing import Dict, Any, List
from ..base import BaseProcessor


class BlurProcessor(BaseProcessor):
    def process(self, image: np.ndarray, params: Dict[str, Any]) -> np.ndarray:
        k = int(params.get("kernel_size", 5))
        if k % 2 == 0:
            k += 1
        return cv2.GaussianBlur(image, (k, k), 0)

    def get_name(self) -> str:
        return "Размытие"

    def get_params_schema(self) -> List[Dict]:
        return [
            {"key": "kernel_size", "type": "int", "min": 1, "max": 31, "default": 5},
        ]
