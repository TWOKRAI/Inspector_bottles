"""StitcherPlugin -- склейка регионов в единый кадр.

Processing-плагин (fan-in N:1): process(items) -> [stitched_item].
Получает уже собранную коллекцию регионов от InspectorManager,
размещает на canvas по координатам.

Порядок наложения: сначала default (фон), затем остальные регионы поверх.
"""

from __future__ import annotations

import time

import numpy as np

from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins.port import Port
from multiprocess_framework.modules.process_module.plugins.registry import register_plugin


@register_plugin("stitcher", category="processing", description="Склейка регионов в единый кадр")
class StitcherPlugin(ProcessModulePlugin):
    """Склейка регионов по координатам на canvas. Fan-in N:1."""

    name = "stitcher"
    category = "processing"

    inputs = [
        Port(name="region", dtype="image/bgr", shape="(H, W, 3)", description="Обработанный регион"),
    ]
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Склеенный кадр"),
    ]

    commands = {}

    def configure(self, ctx: PluginContext) -> None:
        """Настройка: ожидаемые регионы."""
        cfg = ctx.config
        self._camera_id: int = cfg.get("camera_id", 0)
        self._expected_regions: list[str] = cfg.get("expected_regions", [])

        ctx.log_info(
            f"StitcherPlugin[{self._camera_id}]: configured, "
            f"expected_regions={self._expected_regions}"
        )

    def process(self, items: list[dict]) -> list[dict]:
        """Склейка коллекции регионов на canvas.

        items -- коллекция регионов (уже собранная InspectorManager по seq_id).
        Возвращает [{"frame": canvas, ...}] или [].
        """
        if not items:
            return []

        canvas = self._stitch(items)
        if canvas is None:
            return []

        return [{
            "frame": canvas,
            "camera_id": self._camera_id,
            "seq_id": items[0].get("seq_id", 0),
            "frame_id": items[0].get("frame_id", 0),
            "timestamp": time.monotonic(),
            "width": canvas.shape[1],
            "height": canvas.shape[0],
            "channels": 3,
        }]

    def _stitch(self, items: list[dict]) -> np.ndarray | None:
        """Склеить регионы на canvas по координатам из метаданных."""
        # Определяем canvas size из метаданных
        canvas_w = 0
        canvas_h = 0
        for item in items:
            cw = item.get("canvas_width", 0)
            ch = item.get("canvas_height", 0)
            if cw > 0 and ch > 0:
                canvas_w = max(canvas_w, cw)
                canvas_h = max(canvas_h, ch)

        if canvas_w == 0 or canvas_h == 0:
            return None

        canvas = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)

        # Порядок: default_region первым (фон), затем остальные поверх
        sorted_items = sorted(
            items,
            key=lambda it: 0 if "default" in it.get("region_name", "") else 1,
        )

        for item in sorted_items:
            frame = item.get("frame")
            if frame is None:
                continue

            ox = int(item.get("original_x", 0))
            oy = int(item.get("original_y", 0))
            rh, rw = frame.shape[:2]

            # Safe-clamp к canvas
            x1, y1 = max(0, ox), max(0, oy)
            x2 = min(canvas_w, ox + rw)
            y2 = min(canvas_h, oy + rh)

            src_x1 = x1 - ox
            src_y1 = y1 - oy
            src_x2 = src_x1 + (x2 - x1)
            src_y2 = src_y1 + (y2 - y1)

            if x2 > x1 and y2 > y1:
                canvas[y1:y2, x1:x2] = frame[src_y1:src_y2, src_x1:src_x2]

        return canvas
