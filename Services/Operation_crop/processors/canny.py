"""Canny — детекция границ."""

import cv2
import numpy as np
from typing import Dict, Any, List
from ..base import BaseProcessor


class CannyProcessor(BaseProcessor):
    def process(self, image: np.ndarray, params: Dict[str, Any]) -> np.ndarray:
        if len(image.shape) == 3:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        t1 = int(params.get("threshold1", 30))
        t2 = int(params.get("threshold2", 90))
        edges = cv2.Canny(image, t1, t2)
        return cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)

    def get_name(self) -> str:
        return "Canny (границы)"

    def get_params_schema(self) -> List[Dict]:
        return [
            {"key": "threshold1", "type": "int", "min": 0, "max": 255, "default": 30},
            {"key": "threshold2", "type": "int", "min": 0, "max": 255, "default": 90},
        ]
