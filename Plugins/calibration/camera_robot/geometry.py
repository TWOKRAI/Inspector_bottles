"""geometry.py — чистая математика калибровки камера↔робот↔энкодер (P7).

Без I/O, без ctx, без register — только numpy/cv2. Тестируется на синтетике
оффлайн (см. ``tests/test_geometry.py``), до плагина и до железа.

Модель (зоны камеры и робота разнесены лентой):
  - **Гомография H** маппит пиксель → мм робота в системе координат МОМЕНТА захвата
    кадра (энкодер E0). Фитится по 4 углам эталона; центральная (5-я) точка —
    независимая проверка точности (reprojection error).
  - **Вектор ленты** (``mm_per_count`` + ``belt_dir``) описывает, как объект дрейфует
    по ленте: смещение в мм на один счётчик энкодера и направление в осях робота.

Инвариант: H(px) = «робот-мм объекта в момент его захвата». В проде объект,
снятый при энкодере ``E_cap``, к моменту пикинга ``E_pick`` уезжает на
``(E_pick − E_cap)·mm_per_count·belt_dir`` — см. :func:`project_to_pick`.

Belt-компенсация (:func:`compensate`) делает обратное: точку, замеренную роботом
позже (больший энкодер — лента уехала дальше), «отматывает назад» к кадру при E0,
чтобы px[i] и mm[i] относились к одному моменту и H фитилась чисто.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

Vec2 = tuple[float, float]

# Пороги вырождения (мм / безразмерные). Подобраны под мм-масштаб реальной сцены;
# синтетика в тестах использует заведомо ненулевые либо точно нулевые значения.
_EPS_MM = 1e-9
_EPS_DET = 1e-12
_EPS_W = 1e-9


def belt_vector(r1: Vec2, r2: Vec2, enc_a: int, enc_b: int) -> tuple[float, Vec2]:
    """Масштаб и направление ленты из двух касаний ОДНОЙ реперной точки.

    Точка на ленте при энкодере ``enc_a`` была в ``r1`` (мм робота), после прогона
    ленты при ``enc_b`` — в ``r2``. Возвращает ``(mm_per_count, belt_dir)``:
      - ``mm_per_count`` — модуль смещения точки на один счётчик энкодера, мм/count;
      - ``belt_dir`` — единичный вектор направления движения при РОСТЕ энкодера.

    Raises:
        ValueError: если ``enc_b == enc_a`` (лента не сдвинулась по счётчику) или
            ``|r2 − r1| ≈ 0`` (точка не сместилась — лента стоит/проскальзывает).
    """
    d_enc = enc_b - enc_a
    if d_enc == 0:
        raise ValueError("belt_vector: enc_b == enc_a — нулевой интервал энкодера, масштаб не определён")
    dist = math.hypot(r2[0] - r1[0], r2[1] - r1[1])
    if dist < _EPS_MM:
        raise ValueError("belt_vector: |R2-R1| ~ 0 — точка не сместилась (лента стоит или проскальзывает)")
    # Смещение на один счётчик (вектор) — знак d_enc задаёт направление при росте энкодера.
    per_count_x = (r2[0] - r1[0]) / d_enc
    per_count_y = (r2[1] - r1[1]) / d_enc
    mm_per_count = math.hypot(per_count_x, per_count_y)
    belt_dir = (per_count_x / mm_per_count, per_count_y / mm_per_count)
    return mm_per_count, belt_dir


def compensate(mm: Vec2, enc_i: int, enc0: int, mm_per_count: float, belt_dir: Vec2) -> Vec2:
    """Привести замеренную роботом точку к кадру при энкодере захвата ``enc0``.

    ``mm_fixed = mm − (enc_i − enc0)·mm_per_count·belt_dir``. Отматывает пробег ленты
    между захватом (E0) и касанием (enc_i), убирая постоянный сдвиг из данных под фит H.
    """
    shift = (enc_i - enc0) * mm_per_count
    return (mm[0] - shift * belt_dir[0], mm[1] - shift * belt_dir[1])


def order_points(px: list[Vec2]) -> tuple[list[Vec2], Vec2]:
    """5 точек эталона → ``([TL, TR, BR, BL], center)``.

    Центр = ближайшая к центроиду всех 5. 4 угла классифицируются по сумме/разности
    координат (стандартный метод): TL=min(x+y), BR=max(x+y), TR=max(x−y), BL=min(x−y).
    Порядок детерминирован — px[i] и замеренные роботом mm[i] обязаны соответствовать
    одной физической точке (см. риск №2 в плане).

    Raises:
        ValueError: если точек не ровно 5 или углы не классифицируются однозначно.
    """
    pts = [(float(x), float(y)) for x, y in px]
    if len(pts) != 5:
        raise ValueError(f"order_points: ожидается ровно 5 точек, получено {len(pts)}")
    cx = sum(p[0] for p in pts) / 5.0
    cy = sum(p[1] for p in pts) / 5.0
    center_idx = min(range(5), key=lambda i: (pts[i][0] - cx) ** 2 + (pts[i][1] - cy) ** 2)
    center = pts[center_idx]
    corners = [p for i, p in enumerate(pts) if i != center_idx]

    s = [p[0] + p[1] for p in corners]
    d = [p[0] - p[1] for p in corners]
    tl = corners[s.index(min(s))]
    br = corners[s.index(max(s))]
    tr = corners[d.index(max(d))]
    bl = corners[d.index(min(d))]
    ordered = [tl, tr, br, bl]
    if len(set(ordered)) != 4:
        raise ValueError("order_points: углы не классифицируются однозначно (совпадение/вырождение конфигурации)")
    return ordered, center


def fit_homography(px_corners: list[Vec2], mm_fixed_corners: list[Vec2]) -> np.ndarray:
    """Гомография px → мм по 4 углам (точное решение, method=0).

    Raises:
        ValueError: при ≠4 точках, ``findHomography is None`` или вырожденной H
            (|det| ≈ 0 — углы коллинеарны).
    """
    if len(px_corners) != 4 or len(mm_fixed_corners) != 4:
        raise ValueError("fit_homography: нужно ровно 4 угла на px и на мм")
    src = np.asarray(px_corners, dtype=np.float64)
    dst = np.asarray(mm_fixed_corners, dtype=np.float64)
    h, _ = cv2.findHomography(src, dst, method=0)
    if h is None:
        raise ValueError("fit_homography: findHomography вернул None (вырожденная конфигурация точек)")
    if abs(float(np.linalg.det(h))) < _EPS_DET:
        raise ValueError("fit_homography: гомография вырождена (|det| ~ 0) — углы коллинеарны?")
    return h


def apply_homography(h: np.ndarray, px: Vec2) -> Vec2:
    """Применить гомографию к пикселю: ``mm = H·[x, y, 1]`` с нормировкой на w.

    Raises:
        ValueError: если ``w ≈ 0`` (точка на «линии горизонта» гомографии).
    """
    v = np.asarray(h, dtype=np.float64) @ np.array([px[0], px[1], 1.0], dtype=np.float64)
    w = float(v[2])
    if abs(w) < _EPS_W:
        raise ValueError("apply_homography: w ~ 0 — точка вне области определения гомографии")
    return (float(v[0] / w), float(v[1] / w))


def reprojection_error(
    h: np.ndarray,
    px: list[Vec2],
    mm_fixed: list[Vec2],
    center_index: int | None = None,
) -> dict:
    """Ошибка перепроекции H в мм: ``||H(px[i]) − mm_fixed[i]||`` по каждой точке.

    Для калибровки по 4 углам их собственная ошибка ≈ 0 by construction (8 уравнений =
    8 DOF) — реально информативна только 5-я точка (центр), поэтому при заданном
    ``center_index`` дополнительно возвращается ключ ``center_mm``.

    Returns:
        ``{"per_point_mm": [...], "mean_mm": float, "max_mm": float[, "center_mm": float]}``.
    """
    if len(px) != len(mm_fixed):
        raise ValueError("reprojection_error: длины px и mm_fixed не совпадают")
    per_point: list[float] = []
    for p, m in zip(px, mm_fixed):
        pr = apply_homography(h, p)
        per_point.append(math.hypot(pr[0] - m[0], pr[1] - m[1]))
    out: dict = {
        "per_point_mm": per_point,
        "mean_mm": (sum(per_point) / len(per_point)) if per_point else 0.0,
        "max_mm": max(per_point) if per_point else 0.0,
    }
    if center_index is not None:
        out["center_mm"] = per_point[center_index]
    return out


def project_to_pick(
    h: np.ndarray,
    px: Vec2,
    enc_cap: int,
    enc_pick: int,
    mm_per_count: float,
    belt_dir: Vec2,
) -> Vec2:
    """Прод-формула: мм-цель для робота с учётом пробега ленты.

    Объект снят в ``px`` при энкодере ``enc_cap``; к моменту пикинга ``enc_pick`` лента
    увезла его на ``(enc_pick − enc_cap)·mm_per_count·belt_dir``.
    """
    base = apply_homography(h, px)
    shift = (enc_pick - enc_cap) * mm_per_count
    return (base[0] + shift * belt_dir[0], base[1] + shift * belt_dir[1])
