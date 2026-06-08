"""OverlayDrawPlugin — рисует draw-params (overlay) на кадре через cv2.

Многовходовый узел: frame + overlay приходят слитыми в один item (их коррелирует
JoinInspectorManager по seq_id+data_type — см. Этап 1). Здесь — чистая отрисовка:
разворачивает семантику vline в отрезки «от края до края», рисует пунктирные границы
полосы, точки и подписи. Цвет резолвится по таблице (per-shape → group → type → дефолт).

Stateless (слияние сделал Join) → thread_safe=True. Кадр не мутируется (рисуем на копии).
"""

from __future__ import annotations

import cv2

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    ProcessModulePlugin,
    Port,
    for_each,
    register_plugin,
)

from .geometry import vline_segments
from .registers import OverlayDrawRegisters


@register_plugin("overlay_draw", category="rendering", description="Рисует overlay (линии/полосы/точки) на кадре")
class OverlayDrawPlugin(ProcessModulePlugin):
    """frame + overlay → rendered_frame (cv2)."""

    name = "overlay_draw"
    category = "rendering"
    thread_safe = True

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Исходный кадр"),
        Port(name="overlay", dtype="dict", shape="-", description="Draw-params (vlines/lines/points)"),
    ]
    outputs = [
        # Перезаписываем "frame" (конвенция framework: SHM→дисплей кеется на "frame",
        # как contour_draw). Отдельный "rendered_frame" дисплей-путём НЕ читается.
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Кадр с нарисованным overlay"),
    ]

    register_class = OverlayDrawRegisters

    def configure(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._reg: OverlayDrawRegisters = self._init_register(ctx)
        ctx.log_info(f"OverlayDrawPlugin: color_table={len(self._reg.color_table)} строк")

    # --- Резолв стиля: per-shape color → group → type → дефолт ---

    def _resolve(self, shape: dict, kind: str) -> dict:
        r = self._reg
        style: dict = {}
        group = shape.get("group")
        stype = shape.get("type") or kind
        # 1) строка таблицы по group (если задан), затем по type
        for row in r.color_table:
            if group and row.get("group") == group:
                style = dict(row)
                break
        else:
            for row in r.color_table:
                if row.get("type") == stype:
                    style = dict(row)
                    break
        # 2) per-shape явные значения перебивают таблицу
        for k in ("color", "thickness", "radius"):
            if k in shape:
                style[k] = shape[k]
        # 3) дефолты
        default_color = r.default_point_color if kind == "point" else r.default_line_color
        color = style.get("color", default_color)
        return {
            "color": tuple(int(c) for c in color),
            "thickness": int(style.get("thickness", r.default_thickness)),
            "radius": int(style.get("radius", r.default_point_radius)),
        }

    def _draw_dashed(self, canvas, p1, p2, color, thickness) -> None:
        import math

        x1, y1 = p1
        x2, y2 = p2
        length = math.hypot(x2 - x1, y2 - y1)
        if length < 1:
            return
        dash, gap = self._reg.dash_len, self._reg.gap_len
        step = dash + gap
        ux, uy = (x2 - x1) / length, (y2 - y1) / length
        d = 0.0
        while d < length:
            a = (x1 + ux * d, y1 + uy * d)
            b_end = min(d + dash, length)
            b = (x1 + ux * b_end, y1 + uy * b_end)
            cv2.line(canvas, (int(a[0]), int(a[1])), (int(b[0]), int(b[1])), color, thickness)
            d += step

    # --- Обработка ---

    @for_each
    def process(self, item: dict) -> dict | None:
        frame = item.get("frame")
        if frame is None:
            return None
        overlay = item.get("overlay") or {}
        canvas = frame.copy()
        h, w = frame.shape[:2]

        # vlines: семантика линии → центральная линия + 2 пунктирные границы полосы.
        for vl in overlay.get("vlines", []):
            central, plus, minus = vline_segments(
                vl.get("cx", w / 2),
                vl.get("cy", h / 2),
                vl.get("angle", 0.0),
                vl.get("zone_width", 0),
                w,
                h,
            )
            line_style = self._resolve(vl, "line")
            if central:
                cv2.line(canvas, _pt(central[0]), _pt(central[1]), line_style["color"], line_style["thickness"])
            dash_style = self._resolve({"type": "dashed", "group": vl.get("group")}, "dashed")
            for edge in (plus, minus):
                if edge:
                    self._draw_dashed(canvas, edge[0], edge[1], dash_style["color"], dash_style["thickness"])

        # Явные линии (p1/p2).
        for ln in overlay.get("lines", []):
            st = self._resolve(ln, "line")
            cv2.line(canvas, _pt(ln["p1"]), _pt(ln["p2"]), st["color"], st["thickness"])
        for ln in overlay.get("dashed_lines", []):
            st = self._resolve(ln, "dashed")
            self._draw_dashed(canvas, ln["p1"], ln["p2"], st["color"], st["thickness"])

        # Точки + подписи.
        for pt in overlay.get("points", []):
            st = self._resolve(pt, "point")
            xy = _pt(pt["xy"])
            cv2.circle(canvas, xy, st["radius"], st["color"], -1)
            label = pt.get("label")
            if label and self._reg.show_labels:
                cv2.putText(
                    canvas,
                    str(label),
                    (xy[0] + 6, xy[1] - 6),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.4,
                    st["color"],
                    1,
                    cv2.LINE_AA,
                )

        return {**item, "frame": canvas}


def _pt(p) -> tuple[int, int]:
    return (int(round(p[0])), int(round(p[1])))
