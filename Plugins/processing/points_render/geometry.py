"""Рендер карты точек робота: точки + путь (pen-down/pen-up) + лист на холсте.

Чистая функция (тестируемая отдельно от плагина). Точки приходят в мм
(robot-координаты).

Ориентация:
- если задан ``bounds`` = упорядоченные углы листа ``[x0, y0, x1, y1]`` (ЛВ, ПН),
  угол ЛВ (x0,y0) ставится в ВЕРХ-ЛЕВО холста, ПН (x1,y1) — в НИЗ-ПРАВО. Так превью
  совпадает с физлистом при любом знаке Y (не нужно гадать «Y вверх/вниз»);
- ``flip_y`` переворачивает по вертикали ТОЛЬКО рисунок (точки/путь) — для
  визуализации «вверх ногами»; прямоугольник листа и подписи углов остаются на месте;
- без ``bounds`` — bbox-fit по точкам с инверсией Y (legacy, робот Y-вверх).
"""

from __future__ import annotations

import cv2
import numpy as np

# Цвета BGR
_GREEN = (0, 170, 0)  # pen down — рисование
_RED = (0, 0, 220)  # pen up — холостой ход
_SHEET = (150, 150, 150)  # прямоугольник листа робота
_CORNER = (200, 120, 0)  # угловые маркеры (синие)
_LABEL = (60, 60, 60)  # подпись координат


def render_points(
    points: list[dict],
    width: int = 640,
    height: int = 480,
    *,
    bounds: tuple[float, float, float, float] | None = None,
    bg_white: bool = True,
    dot_radius: int = 2,
    show_travel: bool = True,
    show_sheet: bool = True,
    flip_y: bool = False,
    swap_axes: bool = False,
    margin: int = 16,
) -> np.ndarray:
    """Точки робота [{x_mm, y_mm, pen}] → BGR-холст с точками, путём и листом.

    pen=1 — зелёная линия рисования; pen=0 — красный пунктир холостого хода.
    bounds=(x0,y0,x1,y1) — УПОРЯДОЧЕННЫЕ углы листа (ЛВ, ПН): фиксированное окно,
    карта не «гуляет». flip_y — перевернуть рисунок по вертикали (визуализация).
    """
    bg = 255 if bg_white else 0
    canvas = np.full((height, width, 3), bg, dtype=np.uint8)
    pts = [p for p in points if isinstance(p, dict) and "x_mm" in p and "y_mm" in p]
    if bounds is None and not pts:
        return canvas

    sheet_corners: list[tuple[float, float]] | None = None

    if bounds is not None:
        # Упорядоченные углы: (x0,y0)=ЛВ, (x1,y1)=ПН. swap_axes: лист повёрнут 90° —
        # экран-горизонт = робот-Y, экран-вертикаль = робот-X (показать рисунок ровно).
        bx0, by0, bx1, by1 = (float(v) for v in bounds)
        span_x = bx1 - bx0
        span_y = by1 - by0
        # Какая робот-ось идёт по горизонтали/вертикали экрана.
        horiz_span = span_y if swap_axes else span_x
        vert_span = span_x if swap_axes else span_y
        bw_mm = max(abs(horiz_span), 1e-6)
        bh_mm = max(abs(vert_span), 1e-6)
        scale = min((width - 2 * margin) / bw_mm, (height - 2 * margin) / bh_mm)
        draw_w = bw_mm * scale
        draw_h = bh_mm * scale

        def _frac(x_mm: float, y_mm: float) -> tuple[float, float]:
            if swap_axes:
                fx = (y_mm - by0) / span_y if span_y else 0.0
                fy = (x_mm - bx0) / span_x if span_x else 0.0
            else:
                fx = (x_mm - bx0) / span_x if span_x else 0.0
                fy = (y_mm - by0) / span_y if span_y else 0.0
            return fx, fy

        def to_px_pt(x_mm: float, y_mm: float) -> tuple[int, int]:
            fx, fy = _frac(x_mm, y_mm)
            if flip_y:  # переворот рисунка по вертикали (только визуализация)
                fy = 1.0 - fy
            return int(round(margin + fx * draw_w)), int(round(margin + fy * draw_h))

        def to_px_corner(x_mm: float, y_mm: float) -> tuple[int, int]:
            fx, fy = _frac(x_mm, y_mm)
            return int(round(margin + fx * draw_w)), int(round(margin + fy * draw_h))

        sheet_corners = [(bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1)]
    else:
        xs = [float(p["x_mm"]) for p in pts]
        ys = [float(p["y_mm"]) for p in pts]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        bw = max(max_x - min_x, 1e-6)
        bh = max(max_y - min_y, 1e-6)
        scale = min((width - 2 * margin) / bw, (height - 2 * margin) / bh)

        def to_px_pt(x_mm: float, y_mm: float) -> tuple[int, int]:
            x = margin + (x_mm - min_x) * scale
            # инверсия Y: робот Y вверх → экран Y вниз (flip_y отменяет инверсию)
            yv = (y_mm - min_y) if flip_y else (max_y - y_mm)
            return int(round(x)), int(round(margin + yv * scale))

        def to_px_corner(x_mm: float, y_mm: float) -> tuple[int, int]:
            return to_px_pt(x_mm, y_mm)

    def to_px(p: dict) -> tuple[int, int]:
        return to_px_pt(float(p["x_mm"]), float(p["y_mm"]))

    # Лист робота: прямоугольник + 4 угла с подписью координат (углы/подписи не флипаются).
    if show_sheet and sheet_corners is not None:
        _draw_sheet(canvas, sheet_corners, to_px_corner)

    # Путь
    prev: tuple[int, int] | None = None
    for p in pts:
        cur = to_px(p)
        if prev is not None:
            if int(p.get("pen", 1)) == 1:
                cv2.line(canvas, prev, cur, _GREEN, 1, cv2.LINE_AA)
            elif show_travel:
                _dashed_line(canvas, prev, cur, _RED, dash=6)
        prev = cur

    # Точки рисования — кружки
    if dot_radius > 0:
        for p in pts:
            if int(p.get("pen", 1)) == 1:
                cv2.circle(canvas, to_px(p), dot_radius, _GREEN, -1)

    return canvas


def _draw_sheet(canvas: np.ndarray, corners: list[tuple[float, float]], to_px_corner) -> None:
    """Прямоугольник листа робота + 4 угла с подписью координат робота (мм).

    corners — упорядоченные углы (мм): ЛВ, ПВ, ПН, ЛН. Подпись = реальные мм робота.
    """
    h, w = canvas.shape[:2]
    px = [to_px_corner(x, y) for x, y in corners]
    poly = [np.array(px, dtype=np.int32)]
    cv2.polylines(canvas, poly, isClosed=True, color=_SHEET, thickness=1, lineType=cv2.LINE_AA)
    for (xmm, ymm), (cx, cy) in zip(corners, px):
        cv2.circle(canvas, (cx, cy), 4, _CORNER, -1, cv2.LINE_AA)
        label = f"({xmm:.0f}, {ymm:.0f})"
        # Текст внутрь холста, чтобы не обрезался у краёв.
        dx = 7 if cx < w // 2 else -7 - 7 * len(label)
        dy = 16 if cy < h // 2 else -8
        org = (max(2, min(w - 4, cx + dx)), max(12, min(h - 4, cy + dy)))
        cv2.putText(canvas, label, org, cv2.FONT_HERSHEY_SIMPLEX, 0.4, _LABEL, 1, cv2.LINE_AA)


def _dashed_line(img: np.ndarray, p1: tuple[int, int], p2: tuple[int, int], color, dash: int = 6) -> None:
    """Пунктирная линия p1→p2 (холостой ход)."""
    x1, y1 = p1
    x2, y2 = p2
    dist = int(round(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5))
    if dist == 0:
        return
    for i in range(0, dist, dash * 2):
        a = i / dist
        b = min((i + dash) / dist, 1.0)
        xa, ya = int(x1 + (x2 - x1) * a), int(y1 + (y2 - y1) * a)
        xb, yb = int(x1 + (x2 - x1) * b), int(y1 + (y2 - y1) * b)
        cv2.line(img, (xa, ya), (xb, yb), color, 1, cv2.LINE_AA)
