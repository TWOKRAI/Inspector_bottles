"""RegionSplitPlugin -- нарезка кадра на регионы с fan-out 1:N.

Processing-плагин: process(items) -> N items.
Каждый выходной item содержит item["target"] для per-item routing (Q1 решение D).
total_regions добавляется в метаданные для InspectorManager (fan-in буферизация).
"""

from __future__ import annotations

import numpy as np

from multiprocess_framework.modules.process_module.generic import frame_trace
from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    ProcessModulePlugin,
    for_each,
)
from multiprocess_framework.modules.process_module.plugins import Port
from multiprocess_framework.modules.process_module.plugins import register_plugin


@register_plugin("region_split", category="processing", description="Нарезка кадра на регионы + fan-out")
class RegionSplitPlugin(ProcessModulePlugin):
    """Нарезка кадра на регионы. 1:N fan-out через item["target"]."""

    name = "region_split"
    category = "processing"
    thread_safe = True

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Входной BGR-кадр"),
    ]
    outputs = [
        Port(name="region", dtype="image/bgr", shape="(H, W, 3)", description="Вырезанный регион"),
    ]

    commands = {}

    def configure(self, ctx: PluginContext) -> None:
        """Настройка: регионы из конфига."""
        cfg = ctx.config
        self._camera_id: int = cfg.get("camera_id", 0)
        self._regions: list[dict] = cfg.get("regions", [])
        self._default_region: dict | None = cfg.get("default_region")

        self._total_regions = len(self._regions) + (1 if self._default_region else 0)

        region_names = [r["name"] for r in self._regions]
        if self._default_region:
            region_names.append(self._default_region["name"])

        ctx.log_info(f"RegionSplitPlugin[{self._camera_id}]: regions={region_names}, total={self._total_regions}")

    @for_each
    def process(self, item: dict) -> list[dict] | None:
        """1:N fan-out: нарезка кадра на регионы.

        Каждый выходной item содержит:
        - target: процесс-получатель (per-item routing)
        - total_regions: количество регионов (для InspectorManager)
        - region_name, original_x/y, canvas_width/height: метаданные для stitcher
        """
        frame = item.get("frame")
        if frame is None:
            return None

        canvas_h, canvas_w = frame.shape[:2]
        result = []

        # Нарезка ROI-регионов
        for r in self._regions:
            crop, metadata = self._split_region(frame, r, canvas_w, canvas_h)
            if crop is not None:
                out_item = {
                    **item,
                    "frame": crop,
                    "target": r.get("target", "stitcher"),
                    "total_regions": self._total_regions,
                    **metadata,
                }
                # Независимая копия trace — каждый регион должен мутировать
                # свой собственный список спанов, а не общий родительский.
                # Гейт под флагом: без INSPECTOR_FRAME_TRACE копия не нужна.
                if frame_trace.enabled():
                    out_item["trace"] = list(item.get("trace", []))
                result.append(out_item)

        # Default region -- полный кадр
        if self._default_region:
            out_item = {
                **item,
                "frame": frame.copy(),
                "target": self._default_region.get("target", "stitcher"),
                "total_regions": self._total_regions,
                "region_name": self._default_region["name"],
                "original_x": 0,
                "original_y": 0,
                "original_width": canvas_w,
                "original_height": canvas_h,
                "canvas_width": canvas_w,
                "canvas_height": canvas_h,
                "width": canvas_w,
                "height": canvas_h,
            }
            # Независимая копия trace — аналогично ROI-регионам выше.
            if frame_trace.enabled():
                out_item["trace"] = list(item.get("trace", []))
            result.append(out_item)

        return result

    def _split_region(
        self,
        frame: np.ndarray,
        region: dict,
        canvas_w: int,
        canvas_h: int,
    ) -> tuple[np.ndarray | None, dict]:
        """Вырезать один регион с safe-clamp к границам кадра."""
        name = region["name"]
        x, y = int(region["x"]), int(region["y"])
        w, h = int(region["width"]), int(region["height"])

        H, W = frame.shape[:2]
        x1, y1 = max(0, x), max(0, y)
        x2, y2 = min(W, x + w), min(H, y + h)

        if x2 <= x1 or y2 <= y1:
            return None, {}

        crop = frame[y1:y2, x1:x2].copy()

        metadata = {
            "region_name": name,
            "original_x": x1,
            "original_y": y1,
            "original_width": x2 - x1,
            "original_height": y2 - y1,
            "canvas_width": canvas_w,
            "canvas_height": canvas_h,
            "width": x2 - x1,
            "height": y2 - y1,
        }
        return crop, metadata
