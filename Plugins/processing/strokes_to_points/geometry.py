"""Геометрия линия→точки: контуры, прореживание, scale+offset → точки робота.

Чистые функции (без cv2-зависимостей кроме findContours/approxPolyDP) — порт из
projects_obsidian/sketch_robot/modules/{strokes,trajectory}.py с добавлением
двух режимов прореживания (равномерный шаг и порог угла поворота).
"""

from __future__ import annotations

import math

import cv2
import numpy as np

# ---------------------------------------------------------------------------- #
# Извлечение полилиний из бинарной маски (порт из strokes.py)
# ---------------------------------------------------------------------------- #


def find_contours(binary: np.ndarray) -> list[np.ndarray]:
    """Контуры бинарной маски → список Nx2 float64 полилиний (пиксели).

    ВНИМАНИЕ: findContours обводит белую область ПО ГРАНИЦЕ — на толстой линии
    это даёт две параллельные линии (контур), а не одну центральную. Для одной
    линии используй centerline-режим (skeletonize + trace_skeleton).
    """
    contours_raw, _ = cv2.findContours(binary, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    result: list[np.ndarray] = []
    for cnt in contours_raw:
        if len(cnt) < 2:
            continue
        cnt = cnt.squeeze()
        if cnt.ndim == 1:
            continue
        # Убрать дублирующиеся соседние точки.
        mask = np.concatenate(([True], np.any(cnt[1:] != cnt[:-1], axis=1)))
        cnt = cnt[mask]
        if len(cnt) >= 2:
            result.append(cnt.astype(np.float64))
    return result


# ---------------------------------------------------------------------------- #
# Центральная линия: скелетизация (1px) + трассировка путей по скелету
# ---------------------------------------------------------------------------- #


def skeletonize_mask(binary: np.ndarray) -> np.ndarray:
    """Бинарная маска → скелет толщиной 1px (uint8 0/255).

    Приоритет: cv2.ximgproc.thinning (opencv-contrib, быстро на C) → scikit-image
    → чистый numpy Zhang-Suen (без зависимостей).
    """
    b = (binary > 0).astype(np.uint8)
    # 1) opencv-contrib (быстро) — приходит вместе с mediapipe
    ximgproc = getattr(cv2, "ximgproc", None)
    if ximgproc is not None and hasattr(ximgproc, "thinning"):
        try:
            return ximgproc.thinning((b * 255).astype(np.uint8))
        except Exception:  # no-health: чистая утилита без ctx — fallback на skimage/numpy ниже
            pass
    # 2) scikit-image
    try:
        from skimage.morphology import skeletonize as _sk

        return (_sk(b > 0).astype(np.uint8)) * 255
    except Exception:  # no-health: optional-import gate (skimage) — fallback на numpy Zhang-Suen
        pass
    # 3) numpy Zhang-Suen
    return _zhang_suen_thin(b) * 255


def _zhang_suen_thin(binary: np.ndarray) -> np.ndarray:
    """Утоньшение Zhang-Suen (векторизованный numpy). binary 0/1 → 0/1 скелет."""
    img = binary.copy().astype(np.uint8)

    def _nb(im: np.ndarray):
        p = np.pad(im, 1)
        return (
            p[0:-2, 1:-1],
            p[0:-2, 2:],
            p[1:-1, 2:],
            p[2:, 2:],
            p[2:, 1:-1],
            p[2:, 0:-2],
            p[1:-1, 0:-2],
            p[0:-2, 0:-2],
        )  # P2,P3,P4,P5,P6,P7,P8,P9

    changed = True
    while changed:
        changed = False
        for step in (0, 1):
            P2, P3, P4, P5, P6, P7, P8, P9 = _nb(img)
            B = P2 + P3 + P4 + P5 + P6 + P7 + P8 + P9
            seq = [P2, P3, P4, P5, P6, P7, P8, P9, P2]
            A = sum(((seq[i] == 0) & (seq[i + 1] == 1)).astype(np.uint8) for i in range(8))
            if step == 0:
                m1 = (P2 * P4 * P6) == 0
                m2 = (P4 * P6 * P8) == 0
            else:
                m1 = (P2 * P4 * P8) == 0
                m2 = (P2 * P6 * P8) == 0
            cond = (img == 1) & (B >= 2) & (B <= 6) & (A == 1) & m1 & m2
            if cond.any():
                img[cond] = 0
                changed = True
    return img


_NB8 = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))


def _straightness(prev: tuple[int, int], cur: tuple[int, int], nxt: tuple[int, int]) -> float:
    """Угол поворота prev→cur→nxt в радианах (0 = прямо, больше = резче)."""
    v1x, v1y = cur[0] - prev[0], cur[1] - prev[1]
    v2x, v2y = nxt[0] - cur[0], nxt[1] - cur[1]
    n1 = math.hypot(v1x, v1y)
    n2 = math.hypot(v2x, v2y)
    if n1 == 0 or n2 == 0:
        return math.pi
    cosang = (v1x * v2x + v1y * v2y) / (n1 * n2)
    return math.acos(max(-1.0, min(1.0, cosang)))


def trace_skeleton(skel: np.ndarray) -> list[np.ndarray]:
    """Скелет (1px, 0/255) → список полилиний-центральных линий (Nx2, x,y).

    Развилки проходятся НАПРЯМУЮ (самое прямое продолжение) — линия не рвётся на
    каждом перекрёстке, получаются длинные непрерывные штрихи и меньше холостых
    ходов. Каждое ребро скелета обходится один раз. Петли тоже извлекаются.
    """
    ys, xs = np.nonzero(skel)
    pixels = set(zip(ys.tolist(), xs.tolist()))
    if not pixels:
        return []

    def neigh(p: tuple[int, int]) -> list[tuple[int, int]]:
        y, x = p
        return [(y + dy, x + dx) for dy, dx in _NB8 if (y + dy, x + dx) in pixels]

    degree = {p: len(neigh(p)) for p in pixels}
    used_edges: set = set()
    polylines: list[list[tuple[int, int]]] = []

    def walk(start: tuple[int, int], first: tuple[int, int]) -> list[tuple[int, int]]:
        path = [start, first]
        used_edges.add(frozenset((start, first)))
        prev, cur = start, first
        while True:
            cands = [n for n in neigh(cur) if n != prev and frozenset((cur, n)) not in used_edges]
            if not cands:
                break
            # На развилке — самое прямое продолжение; на линии — единственный сосед.
            nxt = cands[0] if len(cands) == 1 else min(cands, key=lambda n: _straightness(prev, cur, n))
            used_edges.add(frozenset((cur, nxt)))
            path.append(nxt)
            prev, cur = cur, nxt
            if degree[cur] == 1:  # дошли до конца линии
                break
        return path

    # 1) От концов (degree 1) — естественное начало штриха
    for node in [p for p in pixels if degree[p] == 1]:
        for nb in neigh(node):
            if frozenset((node, nb)) not in used_edges:
                path = walk(node, nb)
                if len(path) >= 2:
                    polylines.append(path)

    # 2) Оставшиеся рёбра от развилок (degree >= 3)
    for node in [p for p in pixels if degree[p] >= 3]:
        for nb in neigh(node):
            if frozenset((node, nb)) not in used_edges:
                path = walk(node, nb)
                if len(path) >= 2:
                    polylines.append(path)

    # 3) Замкнутые петли (все degree==2, не задеты выше)
    for p in pixels:
        if degree[p] == 2 and all(frozenset((p, n)) not in used_edges for n in neigh(p)):
            nbs = neigh(p)
            if nbs:
                path = walk(p, nbs[0])
                if len(path) >= 2:
                    polylines.append(path)

    # (y, x) → (x, y) float
    return [np.array([(x, y) for (y, x) in path], dtype=np.float64) for path in polylines]


def image_mm_bounds(
    width: int,
    height: int,
    *,
    zone_mode: bool = False,
    zone_x0: float = 0.0,
    zone_y0: float = 0.0,
    zone_x1: float = 100.0,
    zone_y1: float = 100.0,
    scale_x: float = 0.1,
    scale_y: float = 0.1,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    flip_y: bool = True,
) -> tuple[float, float, float, float]:
    """Фиксированные мм-границы кадра (углы изображения → мм). Не зависят от контента.

    Используется points_render как стабильное окно, чтобы карта не «гуляла».
    """
    corners = [(0.0, 0.0), (float(width), 0.0), (0.0, float(height)), (float(width), float(height))]
    pts = polylines_to_points(
        [np.array(corners, dtype=np.float64)],
        height,
        width=width,
        zone_mode=zone_mode,
        zone_x0=zone_x0,
        zone_y0=zone_y0,
        zone_x1=zone_x1,
        zone_y1=zone_y1,
        scale_x=scale_x,
        scale_y=scale_y,
        offset_x=offset_x,
        offset_y=offset_y,
        flip_y=flip_y,
    )
    xs = [p["x_mm"] for p in pts]
    ys = [p["y_mm"] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def filter_by_length(strokes: list[np.ndarray], min_len: float, max_len: float = 0.0) -> list[np.ndarray]:
    """Отбросить штрихи короче min_len и (если max_len>0) длиннее max_len пикселей."""
    filtered: list[np.ndarray] = []
    for s in strokes:
        total_len = float(np.sum(np.linalg.norm(np.diff(s, axis=0), axis=1)))
        if total_len < min_len:
            continue
        if max_len > 0 and total_len > max_len:
            continue
        filtered.append(s)
    return filtered


def simplify_dp(stroke: np.ndarray, epsilon: float) -> np.ndarray:
    """Douglas-Peucker упрощение ломаной (cv2.approxPolyDP)."""
    if epsilon <= 0 or len(stroke) < 3:
        return stroke
    pts = stroke.astype(np.float32).reshape(-1, 1, 2)
    approx = cv2.approxPolyDP(pts, epsilon, closed=False)
    out = approx.squeeze().astype(np.float64)
    if out.ndim == 1:  # выродилось в одну точку
        return stroke
    return out


def resample_step(stroke: np.ndarray, step: float) -> np.ndarray:
    """Равномерный ресемплинг полилинии по длине шагом step (px). Концы сохраняются."""
    if step <= 0 or len(stroke) < 2:
        return stroke
    seg_len = np.linalg.norm(np.diff(stroke, axis=0), axis=1)
    cum = np.concatenate(([0.0], np.cumsum(seg_len)))
    total = float(cum[-1])
    if total <= 0:
        return stroke[:1]
    targets = np.arange(0.0, total, step)
    if targets.size == 0 or targets[-1] < total:
        targets = np.append(targets, total)
    xs = np.interp(targets, cum, stroke[:, 0])
    ys = np.interp(targets, cum, stroke[:, 1])
    return np.column_stack([xs, ys])


def reduce_angle(stroke: np.ndarray, angle_threshold_deg: float) -> np.ndarray:
    """Оставить вершины, где поворот направления линии >= порога (в градусах)."""
    n = len(stroke)
    if n <= 2 or angle_threshold_deg <= 0:
        return stroke
    thr = math.radians(angle_threshold_deg)
    keep = [0]
    for i in range(1, n - 1):
        v1 = stroke[i] - stroke[i - 1]
        v2 = stroke[i + 1] - stroke[i]
        n1 = float(np.linalg.norm(v1))
        n2 = float(np.linalg.norm(v2))
        if n1 == 0.0 or n2 == 0.0:
            continue
        cosang = float(np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0))
        turn = math.acos(cosang)  # 0 = прямая, больше = резче поворот
        if turn >= thr:
            keep.append(i)
    keep.append(n - 1)
    return stroke[keep]


def sort_nearest_neighbor(strokes: list[np.ndarray]) -> list[np.ndarray]:
    """Сортировка штрихов ближайшим соседом — минимизирует холостые ходы."""
    if len(strokes) <= 1:
        return strokes
    ordered = [strokes[0]]
    remaining = list(strokes[1:])
    current_end = ordered[-1][-1]
    while remaining:
        starts = np.array([s[0] for s in remaining])
        dists = np.linalg.norm(starts - current_end, axis=1)
        idx = int(np.argmin(dists))
        ordered.append(remaining.pop(idx))
        current_end = ordered[-1][-1]
    return ordered


def extract_polylines(
    binary: np.ndarray,
    *,
    centerline: bool = True,
    reduce_mode: str = "dp",
    simplify_epsilon: float = 1.0,
    step_px: float = 5.0,
    angle_threshold_deg: float = 15.0,
    min_stroke_len: float = 10.0,
    max_stroke_len: float = 0.0,
) -> list[np.ndarray]:
    """Бинарная маска → отфильтрованные, прореженные и отсортированные полилинии (px).

    centerline=True (по умолчанию): скелетизация (1px) + трассировка центральных
    линий — на толстом штрихе ОДНА линия, а не контур из двух. centerline=False:
    findContours (обводка границы — две линии на толстом штрихе).
    """
    if centerline:
        skel = skeletonize_mask(binary)
        strokes = trace_skeleton(skel)
    else:
        strokes = find_contours(binary)
    strokes = filter_by_length(strokes, min_stroke_len, max_stroke_len)

    mode = (reduce_mode or "dp").lower()
    reduced: list[np.ndarray] = []
    for s in strokes:
        if mode == "dp":
            r = simplify_dp(s, simplify_epsilon)
        elif mode == "step":
            r = resample_step(s, step_px)
        elif mode == "angle":
            r = reduce_angle(s, angle_threshold_deg)
        else:  # "none" — без прореживания
            r = s
        if len(r) >= 2:
            reduced.append(r)

    return sort_nearest_neighbor(reduced)


# ---------------------------------------------------------------------------- #
# Полилинии (px) → точки робота (мм + перо)
# ---------------------------------------------------------------------------- #


def polylines_to_points(
    polylines: list[np.ndarray],
    height: int,
    *,
    width: int = 0,
    zone_mode: bool = False,
    zone_x0: float = 0.0,
    zone_y0: float = 0.0,
    zone_x1: float = 100.0,
    zone_y1: float = 100.0,
    scale_x: float = 0.1,
    scale_y: float = 0.1,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    flip_y: bool = True,
    max_points: int = 0,
) -> list[dict]:
    """Полилинии в пикселях → [{x_mm, y_mm, pen}].

    Первая точка каждого штриха — подвод с поднятым пером (pen=0), остальные —
    рисование (pen=1). max_points>0 обрезает путь ПО ШТРИХАМ (не рвёт геометрию).

    Два режима перевода px→мм:
    - zone_mode=True: изображение [0..W]×[0..H] вписывается в прямоугольник робота
      с углами (zone_x0,zone_y0) ЛВ и (zone_x1,zone_y1) ПН. Ориентацию по Y задаёшь
      сам значениями углов (для робота Y-вверх ставь y0 > y1).
    - zone_mode=False: x=px*scale_x+offset_x, y=(flip)·scale_y+offset_y.
    """
    use_zone = zone_mode and width > 0 and height > 0

    def to_mm(px: float, py: float) -> tuple[float, float]:
        if use_zone:
            x = zone_x0 + px * (zone_x1 - zone_x0) / width
            y = zone_y0 + py * (zone_y1 - zone_y0) / height
            return x, y
        y_src = (height - 1 - py) if flip_y else py
        return px * scale_x + offset_x, y_src * scale_y + offset_y

    points: list[dict] = []
    for poly in polylines:
        if len(poly) < 2:
            continue
        if max_points > 0 and points and len(points) + len(poly) > max_points:
            break
        x0, y0 = to_mm(float(poly[0][0]), float(poly[0][1]))
        points.append({"x_mm": x0, "y_mm": y0, "pen": 0})
        for pt in poly[1:]:
            x, y = to_mm(float(pt[0]), float(pt[1]))
            points.append({"x_mm": x, "y_mm": y, "pen": 1})
    return points
