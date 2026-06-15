"""Рендер карты точек робота: точки + путь (pen-down/pen-up) на холсте.

Чистая функция (тестируемая отдельно от плагина). Точки приходят в мм
(robot-координаты); для наглядности вписываются в холст по bbox с инверсией Y
(робот: Y вверх → экран: Y вниз).
"""

from __future__ import annotations

import cv2
import numpy as np

# Цвета BGR
_GREEN = (0, 170, 0)  # pen down — рисование
_RED = (0, 0, 220)  # pen up — холостой ход


def render_points(
    points: list[dict],
    width: int = 640,
    height: int = 480,
    *,
    bounds: tuple[float, float, float, float] | None = None,
    bg_white: bool = True,
    dot_radius: int = 2,
    show_travel: bool = True,
    margin: int = 16,
) -> np.ndarray:
    """Точки робота [{x_mm, y_mm, pen}] → BGR-холст с точками и путём.

    pen=1 — зелёная линия рисования; pen=0 — красный пунктир холостого хода
    (от предыдущей точки к подводу). Точки рисования помечены кружками.

    bounds=(min_x, min_y, max_x, max_y) — ФИКСИРОВАННОЕ окно координат (мм). Если
    задано, карта не «гуляет» (масштаб стабилен между кадрами). Если None —
    bbox-fit по текущим точкам (масштаб прыгает при смене контента).
    """
    bg = 255 if bg_white else 0
    canvas = np.full((height, width, 3), bg, dtype=np.uint8)
    pts = [p for p in points if isinstance(p, dict) and "x_mm" in p and "y_mm" in p]
    if not pts:
        return canvas

    if bounds is not None:
        min_x, min_y, max_x, max_y = bounds
    else:
        xs = [float(p["x_mm"]) for p in pts]
        ys = [float(p["y_mm"]) for p in pts]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
    bw = max(max_x - min_x, 1e-6)
    bh = max(max_y - min_y, 1e-6)
    scale = min((width - 2 * margin) / bw, (height - 2 * margin) / bh)

    def to_px(p: dict) -> tuple[int, int]:
        x = margin + (float(p["x_mm"]) - min_x) * scale
        # инверсия Y: робот Y вверх → экран Y вниз
        y = margin + (max_y - float(p["y_mm"])) * scale
        return int(round(x)), int(round(y))

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
