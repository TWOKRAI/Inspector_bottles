"""PointsRenderPlugin — карта точек робота на дисплей.

Вход: item["draw_points"] (от strokes_to_points). Заменяет item["frame"] на
холст с точками и путём (pen-down зелёный, pen-up красный пунктир) — для
дисплея «Точки». draw_points пробрасывается дальше (robot_draw их отправит).
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    Port,
    ProcessModulePlugin,
    for_each,
    register_plugin,
)

from . import geometry
from .registers import PointsRenderRegisters


@register_plugin(
    "points_render",
    category="processing",
    description="Карта точек робота: точки + путь (pen-down/pen-up) на холсте",
)
class PointsRenderPlugin(ProcessModulePlugin):
    """draw_points → frame (холст с точками и путём)."""

    name = "points_render"
    category = "processing"
    thread_safe = True

    inputs = [
        Port(name="draw_points", dtype="list[dict]", shape="N", optional=True, description="[{x_mm,y_mm,pen}]"),
    ]
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Холст карты точек"),
        Port(name="draw_points", dtype="list[dict]", shape="N", optional=True, description="Точки (pass-through)"),
    ]

    commands: dict[str, str] = {}
    register_class = PointsRenderRegisters

    @classmethod
    def config_class(cls) -> type | None:
        from .config import PointsRenderPluginConfig

        return PointsRenderPluginConfig

    def configure(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._reg: PointsRenderRegisters = self._init_register(ctx)
        ctx.log_info(f"PointsRenderPlugin: canvas={self._reg.canvas_width}x{self._reg.canvas_height}")

    @for_each
    def process(self, item: dict) -> dict | None:
        points = item.get(self._reg.points_source) or []
        raw_bounds = item.get("draw_bounds")
        bounds = (
            tuple(float(v) for v in raw_bounds)
            if isinstance(raw_bounds, (list, tuple)) and len(raw_bounds) == 4
            else None
        )
        canvas = geometry.render_points(
            points if isinstance(points, list) else [],
            int(self._reg.canvas_width),
            int(self._reg.canvas_height),
            bounds=bounds,
            bg_white=bool(self._reg.bg_white),
            dot_radius=int(self._reg.dot_radius),
            show_travel=bool(self._reg.show_travel),
        )
        self._reg.points_last = len(points) if isinstance(points, list) else 0
        return {**item, "frame": canvas}
