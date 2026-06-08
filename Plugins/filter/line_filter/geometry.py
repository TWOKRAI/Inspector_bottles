"""Геометрия виртуальной линии: знаковое расстояние и клиппинг к кадру.

Линия задаётся центром (cx, cy) и углом θ (градусы). Направление линии
d = (cosθ, sinθ); единичная нормаль n = (−sinθ, cosθ). Знаковое расстояние точки
до линии — проекция (p − center) на нормаль: знак = сторона, модуль = расстояние.
"""

from __future__ import annotations

import math

Point = tuple[float, float]


def line_normal(angle_deg: float) -> Point:
    """Единичная нормаль линии под углом angle_deg."""
    t = math.radians(angle_deg)
    return (-math.sin(t), math.cos(t))


def line_direction(angle_deg: float) -> Point:
    """Единичное направление линии под углом angle_deg."""
    t = math.radians(angle_deg)
    return (math.cos(t), math.sin(t))


def signed_distance(p: Point, center: Point, angle_deg: float) -> float:
    """Знаковое расстояние точки p до линии (center, angle). Знак = сторона."""
    nx, ny = line_normal(angle_deg)
    return (p[0] - center[0]) * nx + (p[1] - center[1]) * ny


def _clip_infinite_line(center: Point, direction: Point, w: int, h: int) -> tuple[Point, Point] | None:
    """Пересечение бесконечной прямой (center + t·direction) с прямоугольником
    [0,w]×[0,h] (Liang–Barsky). Возвращает два конца отрезка или None, если
    прямая не пересекает кадр.
    """
    dx, dy = direction
    # Большой параметрический отрезок, который заведомо перекрывает кадр.
    big = float(w + h) * 4 + 1000.0
    x0, y0 = center[0] - dx * big, center[1] - dy * big
    x1, y1 = center[0] + dx * big, center[1] + dy * big

    p = [-(x1 - x0), (x1 - x0), -(y1 - y0), (y1 - y0)]
    q = [x0 - 0.0, float(w) - x0, y0 - 0.0, float(h) - y0]

    t0, t1 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if pi == 0:
            if qi < 0:
                return None  # параллельно границе и вне неё
            continue
        r = qi / pi
        if pi < 0:
            if r > t1:
                return None
            if r > t0:
                t0 = r
        else:
            if r < t0:
                return None
            if r < t1:
                t1 = r

    ax = x0 + t0 * (x1 - x0)
    ay = y0 + t0 * (y1 - y0)
    bx = x0 + t1 * (x1 - x0)
    by = y0 + t1 * (y1 - y0)
    return ((ax, ay), (bx, by))


def line_segment_in_frame(center: Point, angle_deg: float, w: int, h: int) -> tuple[Point, Point] | None:
    """Центральная линия «от края до края» кадра: концы отрезка внутри [0,w]×[0,h]."""
    return _clip_infinite_line(center, line_direction(angle_deg), w, h)


def band_edges_in_frame(
    center: Point, angle_deg: float, zone_width: float, w: int, h: int
) -> tuple[tuple[Point, Point] | None, tuple[Point, Point] | None]:
    """Две границы полосы (±zone_width/2 вдоль нормали), клиппнутые к кадру."""
    nx, ny = line_normal(angle_deg)
    half = zone_width / 2.0
    plus = (center[0] + nx * half, center[1] + ny * half)
    minus = (center[0] - nx * half, center[1] - ny * half)
    d = line_direction(angle_deg)
    return (_clip_infinite_line(plus, d, w, h), _clip_infinite_line(minus, d, w, h))
