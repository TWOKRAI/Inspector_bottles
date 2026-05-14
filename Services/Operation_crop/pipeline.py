"""
Пайплайн: вырез областей -> цепочка для каждой -> объединение результатов.

Данные:
  - regions: [{name, x1, y1, x2, y2}, ...]
  - region_chains: {region_name: [step, ...]}
  - view_mode: "main" | "region" | "list"
  - selected_region: имя выбранной области (для режима region)
"""

from typing import List, Dict, Tuple
import numpy as np

from .regions import crop_all_regions
from .chain import run_chain


def run_pipeline(
    image: np.ndarray,
    regions: List[Dict],
    region_chains: Dict[str, List[Dict]],
    registry=None,
) -> Tuple[np.ndarray, List[Dict]]:
    """
    Запуск полного пайплайна.
    Возвращает: (result_image, results_list)
    result_image — в зависимости от view_mode (здесь всегда объединённый вид)
    results_list — [{name, image, pos, chain_result}, ...]
    """
    if not regions:
        out = image.copy()
        if len(out.shape) == 2:
            import cv2

            out = cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)
        return out, []

    crops = crop_all_regions(image, regions)
    results_list = []

    for name, crop_img, pos in crops:
        chain = region_chains.get(name, [])
        if chain:
            out = run_chain(crop_img, chain, registry)
        else:
            out = crop_img.copy()
        if len(out.shape) == 2:
            out = np.dstack([out] * 3)
        results_list.append({"name": name, "image": out, "pos": pos})

    # Рисуем результаты на главном изображении
    import cv2

    result = image.copy()
    if len(result.shape) == 2:
        result = cv2.cvtColor(result, cv2.COLOR_GRAY2BGR)
    for r in results_list:
        ox, oy = r["pos"]
        h, w = r["image"].shape[:2]
        result[oy : oy + h, ox : ox + w] = r["image"]

    return result, results_list
