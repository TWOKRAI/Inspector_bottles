"""Операция разделения входного кадра на N регионов (ROI-сплит)."""

from __future__ import annotations

import numpy as np

from multiprocess_prototype.services.processor.operations.base import ChainContext


class RegionSplitterOp:
    """Разделить входной кадр на N регионов. multiplicity=dynamic.

    Output ports создаются динамически из params['regions']: для каждого региона
    с name="X" создаётся выход "out_X". Catalog YAML: output_ports=[] (генерируются runtime).

    Безопасный slice — координаты автоматически clamped к границам кадра.
    Если регион выходит за пределы кадра или имеет нулевую площадь — возвращается None.
    """

    def __init__(self) -> None:
        self._regions: list[dict] = []

    def configure(self, params: dict) -> None:
        """Применить параметры. params['regions'] — список dict с ключами name/x/y/width/height."""
        self._regions = list(params.get("regions") or [])

    def execute_dag(self, inputs: dict, context: ChainContext) -> dict[str, np.ndarray | None]:
        """Разрезать кадр по регионам. Возвращает dict {out_<name>: crop | None}."""
        frame = inputs.get("in")
        if frame is None:
            return {f"out_{r['name']}": None for r in self._regions}

        result: dict[str, np.ndarray | None] = {}
        for r in self._regions:
            x, y, w, h = int(r["x"]), int(r["y"]), int(r["width"]), int(r["height"])
            # Безопасный slice — clamp к границам кадра
            H, W = frame.shape[:2]
            x1, y1 = max(0, x), max(0, y)
            x2, y2 = min(W, x + w), min(H, y + h)
            if x2 > x1 and y2 > y1:
                result[f"out_{r['name']}"] = frame[y1:y2, x1:x2].copy()
            else:
                result[f"out_{r['name']}"] = None
        return result

    def execute(self, frame: np.ndarray, context: ChainContext) -> np.ndarray:
        """Protocol-fallback: возвращает первый ненулевой crop или сам frame."""
        result = self.execute_dag({"in": frame}, context)
        return next((v for v in result.values() if v is not None), frame)


__all__ = ["RegionSplitterOp"]
