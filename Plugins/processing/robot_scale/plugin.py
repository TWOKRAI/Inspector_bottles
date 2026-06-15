"""RobotScalePlugin — масштаб пути px → реальные координаты робота (узел «масштаб под робота»).

Разделение ответственности: strokes_to_points формирует путь в ПИКСЕЛЯХ (identity),
а этот узел вписывает пиксельный кадр в прямоугольник реального листа робота по двум
углам (ЛВ/ПН в мм). Так масштабирование под стол робота — отдельная нода, которую
удобно настраивать (в т.ч. из пульта-дашборда через live field-write).

Вход/выход: item["draw_points"] = [{x_mm, y_mm, pen}]. На входе x_mm/y_mm — пиксели,
на выходе — реальные мм робота. Также обновляет item["draw_bounds"] = прямоугольник
листа (для points_render).
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    Port,
    ProcessModulePlugin,
    for_each,
    register_plugin,
)

from .registers import RobotScaleRegisters


@register_plugin(
    "robot_scale",
    category="processing",
    description="Масштаб пути px → реальные мм робота: вписать кадр в лист по углам (ЛВ/ПН)",
)
class RobotScalePlugin(ProcessModulePlugin):
    """draw_points (px) → draw_points (мм) по прямоугольнику листа робота."""

    name = "robot_scale"
    category = "processing"

    inputs = [
        Port(
            name="draw_points",
            dtype="list[dict]",
            shape="N",
            optional=True,
            description="[{x_mm, y_mm, pen}] в пикселях",
        ),
    ]
    outputs = [
        Port(
            name="draw_points",
            dtype="list[dict]",
            shape="N",
            optional=True,
            description="[{x_mm, y_mm, pen}] в реальных мм робота",
        ),
    ]

    commands: dict[str, str] = {}
    register_class = RobotScaleRegisters

    @classmethod
    def config_class(cls) -> type | None:
        from .config import RobotScalePluginConfig

        return RobotScalePluginConfig

    def configure(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._reg: RobotScaleRegisters = self._init_register(ctx)
        ctx.log_info(
            f"RobotScalePlugin: лист ({self._reg.x0},{self._reg.y0})-({self._reg.x1},{self._reg.y1}) мм "
            f"из {self._reg.src_width}x{self._reg.src_height}px"
        )

    @for_each
    def process(self, item: dict) -> dict | None:
        key = self._reg.points_source
        pts = item.get(key)
        if not isinstance(pts, list):
            return item

        w = max(1, int(self._reg.src_width))
        h = max(1, int(self._reg.src_height))
        x0, y0 = float(self._reg.x0), float(self._reg.y0)
        x1, y1 = float(self._reg.x1), float(self._reg.y1)
        sx = (x1 - x0) / w
        sy = (y1 - y0) / h

        out: list[dict] = []
        for p in pts:
            if not isinstance(p, dict) or "x_mm" not in p or "y_mm" not in p:
                continue
            px = float(p["x_mm"])
            py = float(p["y_mm"])
            out.append(
                {
                    "x_mm": x0 + px * sx,
                    "y_mm": y0 + py * sy,
                    "pen": int(p.get("pen", 1)),
                }
            )

        self._reg.points_last = len(out)
        # Границы мм = прямоугольник листа (для стабильного окна points_render).
        bounds = [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
        return {**item, key: out, "draw_bounds": bounds}
