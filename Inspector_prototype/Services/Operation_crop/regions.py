"""
Области выреза (прямоугольники) на изображении.

Каждая область: name, x1, y1, x2, y2.
Список областей можно редактировать в UI.
"""

from typing import List, Dict, Any, Tuple
import numpy as np


def crop_region(image: np.ndarray, region: Dict[str, Any]) -> np.ndarray:
    """Вырезать прямоугольную область. region: {x1, y1, x2, y2}."""
    x1 = int(region["x1"])
    y1 = int(region["y1"])
    x2 = int(region["x2"])
    y2 = int(region["y2"])
    # Нормализуем порядок координат
    x1, x2 = min(x1, x2), max(x1, x2)
    y1, y2 = min(y1, y2), max(y1, y2)
    return image[y1:y2, x1:x2].copy()


def crop_all_regions(image: np.ndarray, regions: List[Dict]) -> List[Tuple[str, np.ndarray, Tuple[int, int]]]:
    """
    Вырезать все области.
    Возвращает: [(name, crop_image, (offset_x, offset_y)), ...]
    offset — позиция левого верхнего угла выреза на исходном изображении.
    """
    result = []
    for r in regions:
        name = r.get("name", "unnamed")
        x1 = int(r["x1"])
        y1 = int(r["y1"])
        x2 = int(r["x2"])
        y2 = int(r["y2"])
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)
        crop = image[y1:y2, x1:x2].copy()
        result.append((name, crop, (x1, y1)))
    return result
