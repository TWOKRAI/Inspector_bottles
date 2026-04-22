"""Бинаризация."""

import cv2
import numpy as np
from typing import Dict, Any, List
from ..base import BaseProcessor


class ThresholdProcessor(BaseProcessor):
    def process(self, image: np.ndarray, params: Dict[str, Any]) -> np.ndarray:
        if len(image.shape) == 3:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        thresh = int(params.get("thresh", 128))
        _, binary = cv2.threshold(image, thresh, 255, cv2.THRESH_BINARY)
        return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)

    def get_name(self) -> str:
        return "Бинаризация"

    def get_params_schema(self) -> List[Dict]:
        return [
            {"key": "thresh", "type": "int", "min": 0, "max": 255, "default": 128},
        ]
