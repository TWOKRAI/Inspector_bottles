"""Поиск горизонтальных линий (Hough)."""

import cv2
import numpy as np
from typing import Dict, Any, List
from ..base import BaseProcessor
from ..preobrazovanie import detect_horizontal_lines as detect_lines


class DetectHorizontalLinesProcessor(BaseProcessor):
    """Находит горизонтальные линии, рисует их на изображении."""

    def process(self, image: np.ndarray, params: Dict[str, Any]) -> np.ndarray:
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()
        lines, _ = detect_lines(
            gray,
            canny_threshold1=int(params.get("canny_threshold1", 30)),
            canny_threshold2=int(params.get("canny_threshold2", 90)),
            hough_threshold=int(params.get("hough_threshold", 50)),
            min_line_length=int(params.get("min_line_length", 50)),
            max_line_gap=int(params.get("max_line_gap", 20)),
            angle_tolerance=int(params.get("angle_tolerance", 5)),
            morph_size=int(params.get("morph_size", 10)),
        )
        result = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        for (x1, y1, x2, y2) in lines:
            cv2.line(result, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(result, f"Lines: {len(lines)}", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        return result

    def get_name(self) -> str:
        return "Горизонтальные линии"

    def get_params_schema(self) -> List[Dict]:
        return [
            {"key": "canny_threshold1", "type": "int", "min": 0, "max": 255, "default": 30},
            {"key": "canny_threshold2", "type": "int", "min": 0, "max": 255, "default": 90},
            {"key": "hough_threshold", "type": "int", "min": 1, "max": 200, "default": 50},
            {"key": "min_line_length", "type": "int", "min": 1, "max": 200, "default": 50},
            {"key": "max_line_gap", "type": "int", "min": 1, "max": 100, "default": 20},
            {"key": "angle_tolerance", "type": "int", "min": 0, "max": 90, "default": 5},
            {"key": "morph_size", "type": "int", "min": 0, "max": 31, "default": 10},
        ]
