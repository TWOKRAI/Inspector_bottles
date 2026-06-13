"""CircleDrawPlugin -- рисует окружности из item['detections'] на кадре (для дисплея).

Rendering-плагин: frame + detections → frame с нарисованными окружностями (на КОПИИ,
оригинал не трогаем). Аналог contour_draw, но для кругов (center, radius). Нужен,
чтобы показывать детекцию на дисплее, НЕ пачкая кадр, который идёт в center_crop.

Stateless → thread_safe=True. Выходной ключ — 'frame' (конвенция: дисплей читает frame).
"""

from __future__ import annotations

import cv2

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    Port,
    ProcessModulePlugin,
    for_each,
    register_plugin,
)

from .registers import CircleDrawRegisters


@register_plugin("circle_draw", category="rendering", description="Рисует окружности (detections) на кадре")
class CircleDrawPlugin(ProcessModulePlugin):
    """frame + detections(center, radius) → frame с окружностями (на копии)."""

    name = "circle_draw"
    category = "rendering"
    thread_safe = True

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Исходный кадр"),
        Port(name="detections", dtype="list[dict]", shape="N", description="Окружности (center, radius)"),
    ]
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Кадр с окружностями"),
    ]

    register_class = CircleDrawRegisters

    def configure(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._reg: CircleDrawRegisters = self._init_register(ctx)
        ctx.log_info(f"CircleDrawPlugin: color={self._reg.color_bgr}, thickness={self._reg.thickness}")

    @for_each
    def process(self, item: dict) -> dict | None:
        frame = item.get("frame")
        if frame is None:
            return None
        detections = item.get("detections")
        if not isinstance(detections, list) or not detections:
            return item  # нечего рисовать — кадр без изменений

        canvas = frame.copy()
        color = tuple(int(c) for c in self._reg.color_bgr)
        thickness = int(self._reg.thickness)
        for det in detections:
            if not isinstance(det, dict):
                continue
            ctr = det.get("center")
            r = det.get("radius")
            if not isinstance(ctr, (list, tuple)) or len(ctr) < 2 or r is None:
                continue
            cx, cy = int(ctr[0]), int(ctr[1])
            cv2.circle(canvas, (cx, cy), int(r), color, thickness)
            if self._reg.draw_center:
                cv2.circle(canvas, (cx, cy), 2, color, -1)
            if self._reg.show_radius:
                cv2.putText(
                    canvas, f"r={int(r)}", (cx + 4, cy - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA
                )
        return {**item, "frame": canvas}
