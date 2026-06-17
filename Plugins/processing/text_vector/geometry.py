"""Геометрия text_vector: раскладка глифов, матрица 2×2 + сдвиг, → draw_points (px).

Чистые функции (без cv2). Глифы приходят из strokes_font в grid-единицах (Y ВВЕРХ,
baseline 0, CAP сверху). Здесь переводим в пиксели кадра, центрируем, применяем
масштаб/поворот/позицию (req: точные scale/rotation/position) и формируем
[{x_mm, y_mm, pen}] В ПИКСЕЛЯХ — дальше robot_scale впишет в лист робота (тот же
контракт, что у strokes_to_points → весь downstream переиспользуется).
"""

from __future__ import annotations

import math

from . import strokes_font

Point = tuple[float, float]
Polyline = list[Point]


def _grid_to_px(strokes: list[Polyline], pen_x_px: float, scale: float) -> list[Polyline]:
    """Штрихи глифа (grid, Y вверх) → пиксели (Y вниз) со сдвигом pen_x_px по X.

    gx → pen_x_px + gx*scale; gy → (CAP - gy)*scale (верх прописной = 0, baseline = size_px,
    выносной хвост gy<0 → ниже baseline).
    """
    cap = strokes_font.CAP
    out: list[Polyline] = []
    for s in strokes:
        out.append([(pen_x_px + gx * scale, (cap - gy) * scale) for (gx, gy) in s])
    return out


def layout_text(text: str, size_px: float, tracking_px: float = 0.0) -> tuple[list[Polyline], list[str]]:
    """Строка → полилинии (пиксели, origin верх-лево) + список пропущенных символов.

    size_px = высота прописной в пикселях. tracking_px — доп. зазор между ячейками.
    Неизвестный символ пропускается (возвращается в списке skipped) и НЕ рвёт раскладку.
    """
    scale = float(size_px) / strokes_font.CAP
    polylines: list[Polyline] = []
    skipped: list[str] = []
    pen_x = 0.0
    for ch in text:
        g = strokes_font.glyph(ch)
        adv = strokes_font.advance(ch)
        if g is None:
            skipped.append(ch)
            pen_x += adv * scale + tracking_px  # неизвестный → как пробел (раскладка не рвётся)
            continue
        polylines.extend(_grid_to_px(g, pen_x, scale))
        pen_x += adv * scale + tracking_px
    return polylines, skipped


def heart_polylines(size_px: float) -> list[Polyline]:
    """Сердце → полилинии (пиксели, origin верх-лево). size_px = высота."""
    scale = float(size_px) / strokes_font.CAP
    return _grid_to_px(strokes_font.heart(), 0.0, scale)


def bbox(polylines: list[Polyline]) -> tuple[float, float, float, float]:
    """Габариты (minx, miny, maxx, maxy). Пустой вход → нули."""
    pts = [p for poly in polylines for p in poly]
    if not pts:
        return 0.0, 0.0, 0.0, 0.0
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def apply_transform(
    polylines: list[Polyline],
    *,
    scale: float = 1.0,
    rotation_deg: float = 0.0,
    pos_x: float = 0.0,
    pos_y: float = 0.0,
) -> list[Polyline]:
    """Матрица 2×2 (масштаб+поворот вокруг ЦЕНТРА блока) + перенос центра в (pos_x, pos_y).

    Центрирование вокруг bbox-центра делает поворот «на месте», а pos_x/pos_y — куда
    лёг центр (предсказуемо для пульта). Поворот по часовой в экранных координатах
    (Y вниз) при rotation_deg>0.
    """
    if not polylines:
        return []
    minx, miny, maxx, maxy = bbox(polylines)
    cx = (minx + maxx) / 2.0
    cy = (miny + maxy) / 2.0
    rad = math.radians(rotation_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    s = float(scale)
    out: list[Polyline] = []
    for poly in polylines:
        np: Polyline = []
        for x, y in poly:
            dx = (x - cx) * s
            dy = (y - cy) * s
            rx = dx * cos_a - dy * sin_a
            ry = dx * sin_a + dy * cos_a
            np.append((rx + pos_x, ry + pos_y))
        out.append(np)
    return out


def polylines_to_draw_points(polylines: list[Polyline]) -> list[dict]:
    """Полилинии (px) → [{x_mm, y_mm, pen}] (значения — пиксели; robot_scale впишет в лист).

    Первая точка каждой полилинии — подвод с поднятым пером (pen=0), остальные —
    рисование (pen=1). Контракт идентичен strokes_to_points.polylines_to_points.
    """
    points: list[dict] = []
    for poly in polylines:
        if len(poly) < 1:
            continue
        x0, y0 = poly[0]
        points.append({"x_mm": float(x0), "y_mm": float(y0), "pen": 0})
        for x, y in poly[1:]:
            points.append({"x_mm": float(x), "y_mm": float(y), "pen": 1})
    return points


def build_element(
    *,
    element: str,
    text: str,
    size_px: float,
    tracking_px: float,
    scale: float,
    rotation_deg: float,
    pos_x: float,
    pos_y: float,
) -> tuple[list[dict], list[str]]:
    """Собрать элемент (text|heart) → (draw_points px, skipped chars).

    element="text": раскладка строки; "heart": сердце (text игнорируется).
    """
    if element == "heart":
        polys = heart_polylines(size_px)
        skipped: list[str] = []
    else:
        polys, skipped = layout_text(text, size_px, tracking_px)
    polys = apply_transform(polys, scale=scale, rotation_deg=rotation_deg, pos_x=pos_x, pos_y=pos_y)
    return polylines_to_draw_points(polys), skipped
