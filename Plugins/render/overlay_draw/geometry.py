"""Геометрия рендера: клиппинг бесконечной линии/полосы к кадру.

Локальная копия (overlay_draw самодостаточен, без cross-plugin импортов). Разворачивает
семантику vline (center, angle, zone_width) в отрезки «от края до края» по размеру кадра.
"""

from __future__ import annotations

import math

Point = tuple[float, float]


def _normal(angle_deg: float) -> Point:
    t = math.radians(angle_deg)
    return (-math.sin(t), math.cos(t))


def _direction(angle_deg: float) -> Point:
    t = math.radians(angle_deg)
    return (math.cos(t), math.sin(t))


def _clip(center: Point, direction: Point, w: int, h: int) -> tuple[Point, Point] | None:
    """Liang–Barsky: пересечение бесконечной прямой с прямоугольником [0,w]×[0,h]."""
    dx, dy = direction
    big = float(w + h) * 4 + 1000.0
    x0, y0 = center[0] - dx * big, center[1] - dy * big
    x1, y1 = center[0] + dx * big, center[1] + dy * big
    p = [-(x1 - x0), (x1 - x0), -(y1 - y0), (y1 - y0)]
    q = [x0, float(w) - x0, y0, float(h) - y0]
    t0, t1 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if pi == 0:
            if qi < 0:
                return None
            continue
        r = qi / pi
        if pi < 0:
            if r > t1:
                return None
            t0 = max(t0, r)
        else:
            if r < t0:
                return None
            t1 = min(t1, r)
    return (
        (x0 + t0 * (x1 - x0), y0 + t0 * (y1 - y0)),
        (x0 + t1 * (x1 - x0), y0 + t1 * (y1 - y0)),
    )


def vline_segments(
    cx: float, cy: float, angle_deg: float, zone_width: float, w: int, h: int
) -> tuple[tuple[Point, Point] | None, tuple[Point, Point] | None, tuple[Point, Point] | None]:
    """Развернуть vline в (центральная линия, граница +w/2, граница −w/2), клиппнутые к кадру."""
    center = (cx, cy)
    d = _direction(angle_deg)
    nx, ny = _normal(angle_deg)
    half = zone_width / 2.0
    central = _clip(center, d, w, h)
    plus = _clip((cx + nx * half, cy + ny * half), d, w, h)
    minus = _clip((cx - nx * half, cy - ny * half), d, w, h)
    return central, plus, minus
