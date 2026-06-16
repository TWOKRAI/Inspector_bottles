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
        scale = float(self._reg.draw_scale)
        ox, oy = float(self._reg.offset_x), float(self._reg.offset_y)
        swap = bool(self._reg.swap_axes)
        # Какая пиксельная ось кадра управляет какой осью робота. swap=лист повёрнут 90°:
        # робот-X из вертикали кадра (py), робот-Y из горизонтали (px).
        src_x_extent = h if swap else w  # протяжённость источника, управляющего робот-X
        src_y_extent = w if swap else h  # ... робот-Y
        rx = (x1 - x0) / src_x_extent
        ry = (y1 - y0) / src_y_extent
        if bool(self._reg.keep_aspect):
            # Единый масштаб по меньшей стороне → без искажения; центрируем в зоне.
            su = min(abs(rx), abs(ry))
            sx = su * (1.0 if rx >= 0 else -1.0) * scale
            sy = su * (1.0 if ry >= 0 else -1.0) * scale
            pad_x = (abs(x1 - x0) - abs(sx) * src_x_extent) / 2.0 * (1.0 if rx >= 0 else -1.0)
            pad_y = (abs(y1 - y0) - abs(sy) * src_y_extent) / 2.0 * (1.0 if ry >= 0 else -1.0)
        else:
            sx = rx * scale
            sy = ry * scale
            pad_x = pad_y = 0.0

        out: list[dict] = []
        for p in pts:
            if not isinstance(p, dict) or "x_mm" not in p or "y_mm" not in p:
                continue
            px = float(p["x_mm"])
            py = float(p["y_mm"])
            # Источник, управляющий каждой осью робота (swap меняет px↔py роли).
            src_for_x = py if swap else px
            src_for_y = px if swap else py
            out.append(
                {
                    "x_mm": x0 + pad_x + ox + src_for_x * sx,
                    "y_mm": y0 + pad_y + oy + src_for_y * sy,
                    "pen": int(p.get("pen", 1)),
                }
            )

        self._reg.points_last = len(out)
        # Границы мм = УПОРЯДОЧЕННЫЕ углы листа [x0,y0 (ЛВ), x1,y1 (ПН)] — points_render
        # ориентирует превью по ним (ЛВ→верх-лево), совпадая с физлистом при любом знаке Y.
        # Лист (зона A4) фиксирован — рисунок виден ездящим/масштабирующимся внутри.
        bounds = [x0, y0, x1, y1]
        return {**item, key: out, "draw_bounds": bounds}
