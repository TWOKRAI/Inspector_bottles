"""StrokesToPointsPlugin — линия→точки для робота (ядро рисования портрета).

Вход: item["mask"] (бинарная карта линий от blob_filter/edge_detection).
Путь считается НЕПРЕРЫВНО на каждом кадре (контуры → прореживание dp|step|angle
→ сортировка ближайшим соседом → scale+offset → точки робота [{x_mm, y_mm, pen}])
и кладётся в item["draw_points"]. Это нужно для live-карты точек (points_render)
и тюнинга на статичном кадре.

Отправку роботу делает плагин robot_draw по команде (а не этот плагин), поэтому
здесь нет одноразового триггера.

Логика портирована из projects_obsidian/sketch_robot (strokes.py, trajectory.py),
см. geometry.py.
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

from . import geometry
from .registers import StrokesToPointsRegisters


@register_plugin(
    "strokes_to_points",
    category="processing",
    description="Линия→точки робота: контуры, прореживание (dp/step/angle), scale+offset, перо",
)
class StrokesToPointsPlugin(ProcessModulePlugin):
    """mask → (по триггеру) draw_points [{x_mm, y_mm, pen}]; frame passthrough."""

    name = "strokes_to_points"
    category = "processing"
    thread_safe = False  # флаг _armed между вызовами

    inputs = [
        Port(name="mask", dtype="image/gray", shape="(H, W)", description="Бинарная маска линий"),
    ]
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Кадр (pass-through)"),
        Port(
            name="draw_points",
            dtype="list[dict]",
            shape="N",
            optional=True,
            description="[{x_mm, y_mm, pen}] — путь робота (только при триггере)",
        ),
    ]

    commands: dict[str, str] = {}
    register_class = StrokesToPointsRegisters

    @classmethod
    def config_class(cls) -> type | None:
        from .config import StrokesToPointsPluginConfig

        return StrokesToPointsPluginConfig

    def configure(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._reg: StrokesToPointsRegisters = self._init_register(ctx)
        ctx.log_info(
            f"StrokesToPointsPlugin: reduce={self._reg.reduce_mode} "
            f"scale=({self._reg.scale_x},{self._reg.scale_y}) flip_y={self._reg.flip_y}"
        )

    # ------------------------------------------------------------------ #
    # PROCESS — путь считается НЕПРЕРЫВНО (для карты точек live).
    # Отправку роботу делает robot_draw по команде, а не этот плагин.
    # ------------------------------------------------------------------ #

    @for_each
    def process(self, item: dict) -> dict | None:
        mask = item.get("mask")
        if mask is None:
            return item

        points = self._build_points(mask)
        self._reg.points_last = len(points)
        # Фиксированные мм-границы кадра — стабильное окно для points_render
        # (чтобы карта точек не «гуляла» при смене контента).
        bounds = geometry.image_mm_bounds(
            int(mask.shape[1]),
            int(mask.shape[0]),
            zone_mode=bool(self._reg.zone_mode),
            zone_x0=float(self._reg.zone_x0),
            zone_y0=float(self._reg.zone_y0),
            zone_x1=float(self._reg.zone_x1),
            zone_y1=float(self._reg.zone_y1),
            scale_x=float(self._reg.scale_x),
            scale_y=float(self._reg.scale_y),
            offset_x=float(self._reg.offset_x),
            offset_y=float(self._reg.offset_y),
            flip_y=bool(self._reg.flip_y),
        )
        return {**item, "draw_points": points, "draw_bounds": list(bounds)}

    def _build_points(self, mask) -> list[dict]:
        """Бинарная маска → точки робота [{x_mm, y_mm, pen}]."""
        # mask должна быть одноканальной uint8 0/255.
        if mask.ndim == 3:
            mask = cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)

        polylines = geometry.extract_polylines(
            mask,
            centerline=bool(self._reg.centerline),
            reduce_mode=str(self._reg.reduce_mode),
            simplify_epsilon=float(self._reg.simplify_epsilon),
            step_px=float(self._reg.step_px),
            angle_threshold_deg=float(self._reg.angle_threshold_deg),
            min_stroke_len=float(self._reg.min_stroke_len),
            max_stroke_len=float(self._reg.max_stroke_len),
        )
        self._reg.strokes_last = len(polylines)

        points = geometry.polylines_to_points(
            polylines,
            int(mask.shape[0]),
            width=int(mask.shape[1]),
            zone_mode=bool(self._reg.zone_mode),
            zone_x0=float(self._reg.zone_x0),
            zone_y0=float(self._reg.zone_y0),
            zone_x1=float(self._reg.zone_x1),
            zone_y1=float(self._reg.zone_y1),
            scale_x=float(self._reg.scale_x),
            scale_y=float(self._reg.scale_y),
            offset_x=float(self._reg.offset_x),
            offset_y=float(self._reg.offset_y),
            flip_y=bool(self._reg.flip_y),
            max_points=int(self._reg.max_points),
        )
        return points
