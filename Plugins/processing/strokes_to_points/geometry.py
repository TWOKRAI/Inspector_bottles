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


# Таблица «прямизны» для пары направлений (d_in → d_out): угол поворота, как в
# _straightness, но посчитанный один раз для 64 пар. Шаг обхода всегда к одному
# из 8 соседей, поэтому угол зависит только от пары направлений, не от координат.
_TURN = tuple(
    tuple(_straightness((0, 0), _NB8[a], (_NB8[a][0] + _NB8[b][0], _NB8[a][1] + _NB8[b][1])) for b in range(8))
    for a in range(8)
)
# Обратное направление: _NB8[i] и _NB8[7-i] противоположны (проверяется тестом).
_REV = tuple(7 - i for i in range(8))
_TURN_ARR = np.array(_TURN, dtype=np.float64)
_REV_ARR = np.array(_REV, dtype=np.int64)

try:  # Numba опциональна: без неё работает тот же алгоритм на чистом Python.
    from numba import njit as _njit

    _HAS_NUMBA = True
except ImportError:  # pragma: no cover — окружение без numba
    _HAS_NUMBA = False


if _HAS_NUMBA:
    # boundscheck=True обязателен: без него нарушенный инвариант «каждое ребро один
    # раз» (например, ошибка в пометке рёбер) пишет за границу out/offs и даёт не
    # исключение, а порчу кучи — инъекция 2026-09-04 показала зелёный полный набор
    # тестов и крах 0xC0000374 в следующем процессе. Цена проверки измерена ниже
    # в отчёте; ядро зависит от неё, а от ядра — траектория робота.
    @_njit(cache=True, boundscheck=True)
    def _walk_nb(start, d0, nbr, deg, turn, rev, used, out, pos):  # pragma: no cover — numba
        """Один штрих от узла start в направлении d0; id узлов пишутся в out с pos."""
        cur = nbr[start, d0]
        out[pos] = start
        out[pos + 1] = cur
        pos += 2
        used[start * 8 + d0] = 1
        used[cur * 8 + rev[d0]] = 1
        prev = start
        d_in = d0
        while True:
            base = cur * 8
            nxt = -1
            nxt_d = -1
            n_cands = 0
            best = 0.0
            for d in range(8):
                nb = nbr[cur, d]
                if nb < 0 or nb == prev or used[base + d] != 0:
                    continue
                n_cands += 1
                if n_cands == 1:
                    nxt = nb
                    nxt_d = d
                    best = turn[d_in, d]
                else:
                    t = turn[d_in, d]
                    if t < best:
                        nxt = nb
                        nxt_d = d
                        best = t
            if n_cands == 0:
                break
            used[base + nxt_d] = 1
            used[nxt * 8 + rev[nxt_d]] = 1
            out[pos] = nxt
            pos += 1
            prev = cur
            cur = nxt
            d_in = nxt_d
            if deg[cur] == 1:
                break
        return pos

    @_njit(cache=True, boundscheck=True)
    def _trace_all_nb(nbr, deg, turn, rev):  # pragma: no cover — numba
        """Три фазы обхода (концы → развилки → петли). Возвращает (ids, offsets)."""
        n = nbr.shape[0]
        deg_sum = 0
        for i in range(n):
            deg_sum += deg[i]
        n_edges = deg_sum // 2
        used = np.zeros(n * 8, dtype=np.uint8)
        # Каждый штрих = рёбра + 1 узел, штрихов не больше, чем рёбер.
        out = np.empty(2 * n_edges + 2, dtype=np.int64)
        offs = np.empty(n_edges + 2, dtype=np.int64)
        npoly = 0
        pos = 0
        for phase in range(3):
            for node in range(n):
                dg = deg[node]
                if phase == 0 and dg != 1:
                    continue
                if phase == 1 and dg < 3:
                    continue
                base = node * 8
                if phase == 2:
                    if dg != 2:
                        continue
                    free = 0
                    first_d = -1
                    for d in range(8):
                        if nbr[node, d] >= 0 and used[base + d] == 0:
                            free += 1
                            if first_d < 0:
                                first_d = d
                    if free != 2:  # чистая петля — оба ребра не тронуты
                        continue
                    offs[npoly] = pos
                    pos = _walk_nb(node, first_d, nbr, deg, turn, rev, used, out, pos)
                    npoly += 1
                    continue
                # Проверка «ребро не пройдено» в момент итерации: обход по петле
                # может вернуться в этот же узел и занять его второе направление.
                for d in range(8):
                    if nbr[node, d] >= 0 and used[base + d] == 0:
                        offs[npoly] = pos
                        pos = _walk_nb(node, d, nbr, deg, turn, rev, used, out, pos)
                        npoly += 1
        offs[npoly] = pos
        return out[:pos], offs[: npoly + 1]


def trace_skeleton(skel: np.ndarray, *, use_numba: bool | None = None) -> list[np.ndarray]:
    """Скелет (1px, 0/255) → список полилиний-центральных линий (Nx2, x,y).

    Развилки проходятся НАПРЯМУЮ (самое прямое продолжение) — линия не рвётся на
    каждом перекрёстке, получаются длинные непрерывные штрихи и меньше холостых
    ходов. Каждое ребро скелета обходится один раз. Петли тоже извлекаются.

    Реализация на плоских целых индексах (2026-09-04): соседи и степени узлов
    считаются векторно один раз, использованные рёбра лежат в bytearray по
    (узел, направление), прямизна на развилке берётся из таблицы _TURN. Хэшей
    кортежей и frozenset на горячем пути нет. Правило выбора продолжения то же,
    что в исходной реализации (эталон — tests/_reference_trace.py); отличие
    одно: узлы перебираются в растровом порядке, а не в порядке set(), поэтому
    разбиение на штрихи у развилок может отличаться при том же покрытии рёбер.
    Ядро обхода есть в двух исполнениях с одним алгоритмом: numba (@njit,
    _trace_all_nb, используется когда numba установлена) и чистый Python
    (запасной путь для окружений без numba). use_numba=None — авто.
    """
    sk = skel > 0
    if not sk.any():
        return []
    h, w = sk.shape
    # Рамка в 1px снимает проверки границ: у любого узла все 8 соседей внутри массива.
    padded = np.zeros((h + 2, w + 2), dtype=bool)
    padded[1:-1, 1:-1] = sk
    ys, xs = np.nonzero(padded)  # растровый порядок
    n = int(ys.size)
    stride = w + 2
    flat = ys.astype(np.int64) * stride + xs.astype(np.int64)
    node_of = np.full(padded.size, -1, dtype=np.int64)
    node_of[flat] = np.arange(n, dtype=np.int64)
    offs = np.array([dy * stride + dx for dy, dx in _NB8], dtype=np.int64)
    nbr = node_of[flat[:, None] + offs[None, :]]  # n×8, -1 = соседа нет
    deg = (nbr >= 0).sum(axis=1).astype(np.int64)

    xs_f = xs.astype(np.float64) - 1.0  # минус рамка
    ys_f = ys.astype(np.float64) - 1.0

    if use_numba is None:
        use_numba = _HAS_NUMBA
    if use_numba:
        if not _HAS_NUMBA:
            raise RuntimeError("trace_skeleton(use_numba=True): numba не установлена")
        ids, bounds = _trace_all_nb(np.ascontiguousarray(nbr), deg, _TURN_ARR, _REV_ARR)
        # Инвариант обхода: узлов записано ровно (рёбер + штрихов). Любое двойное
        # прохождение ребра ломает равенство — громко, а не тихо (см. boundscheck выше).
        n_edges = int(deg.sum()) // 2
        n_poly = int(bounds.size) - 1
        if int(ids.size) != n_edges + n_poly:
            raise RuntimeError(
                f"trace_skeleton: нарушен инвариант обхода — узлов {int(ids.size)}, "
                f"ожидалось рёбер {n_edges} + штрихов {n_poly}"
            )
        # Координаты собираются ОДНИМ массивом, штрихи — срезы-представления по
        # границам. Сборка по np.stack на каждый штрих стоила ~4 мкс × тысячи
        # штрихов и съедала выигрыш ядра целиком (замер 2026-09-04: 27 мс против
        # ~2 мс ядра). Потребители (filter/simplify/resample) массивы не мутируют.
        pts = np.stack((xs_f[ids], ys_f[ids]), axis=1)
        b = bounds.tolist()
        return [pts[b[i] : b[i + 1]] for i in range(len(b) - 1)]

    nbr_l: list[list[int]] = nbr.tolist()
    deg_l: list[int] = deg.tolist()
    used = bytearray(n * 8)  # used[node*8 + dir] = ребро в этом направлении пройдено
    polylines: list[list[int]] = []

    def walk(start: int, d0: int) -> list[int]:
        cur = nbr_l[start][d0]
        path = [start, cur]
        used[start * 8 + d0] = 1
        used[cur * 8 + _REV[d0]] = 1
        prev, d_in = start, d0
        while True:
            row = nbr_l[cur]
            base = cur * 8
            nxt = -1
            nxt_d = -1
            n_cands = 0
            best = 0.0
            for d in range(8):
                nb = row[d]
                if nb < 0 or nb == prev or used[base + d]:
                    continue
                n_cands += 1
                if n_cands == 1:
                    nxt, nxt_d = nb, d
                    best = _TURN[d_in][d]
                else:
                    # На развилке — самое прямое продолжение; при равенстве первый по _NB8.
                    turn = _TURN[d_in][d]
                    if turn < best:
                        nxt, nxt_d, best = nb, d, turn
            if n_cands == 0:
                break
            used[base + nxt_d] = 1
            used[nxt * 8 + _REV[nxt_d]] = 1
            path.append(nxt)
            prev, cur, d_in = cur, nxt, nxt_d
            if deg_l[cur] == 1:  # дошли до конца линии
                break
        return path

    def walk_all_unused(node: int) -> None:
        # Проверка «ребро не пройдено» — в момент итерации, не заранее: обход по
        # петле может вернуться в этот же узел и занять его второе направление.
        row = nbr_l[node]
        base = node * 8
        for d in range(8):
            if row[d] >= 0 and not used[base + d]:
                polylines.append(walk(node, d))

    # 1) От концов (degree 1) — естественное начало штриха
    for node in range(n):
        if deg_l[node] == 1:
            walk_all_unused(node)

    # 2) Оставшиеся рёбра от развилок (degree >= 3)
    for node in range(n):
        if deg_l[node] >= 3:
            walk_all_unused(node)

    # 3) Замкнутые петли (все degree==2, не задеты выше)
    for node in range(n):
        if deg_l[node] == 2:
            row = nbr_l[node]
            base = node * 8
            dirs = [d for d in range(8) if row[d] >= 0 and not used[base + d]]
            if len(dirs) == 2:  # оба ребра не тронуты — чистая петля
                polylines.append(walk(node, dirs[0]))

    # id узлов → (x, y) float
    out: list[np.ndarray] = []
    for path in polylines:
        ids = np.asarray(path, dtype=np.int64)
        out.append(np.stack((xs_f[ids], ys_f[ids]), axis=1))
    return out


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
    """Сортировка штрихов ближайшим соседом — минимизирует холостые ходы.

    Жадный обход: на каждом шаге берётся штрих, чьё НАЧАЛО ближе всего к КОНЦУ
    предыдущего. Массив начал `starts` строится ОДИН раз, «занятые» гасятся в inf —
    без пересборки массива на каждой итерации (было O(n²) с аллокацией на шаг и
    росло квадратично с числом контуров, роняя FPS на детальных кадрах). Результат
    побайтово тот же: сравнивается квадрат расстояния (монотонен → argmin не меняется),
    ничьи разрешаются по меньшему исходному индексу — как и раньше.
    """
    n = len(strokes)
    if n <= 1:
        return strokes
    starts = np.array([s[0] for s in strokes], dtype=np.float64)  # (n, 2) — один раз
    used = np.zeros(n, dtype=bool)
    order = np.empty(n, dtype=np.int64)
    order[0] = 0
    used[0] = True
    current_end = strokes[0][-1]
    for k in range(1, n):
        delta = starts - current_end
        dist_sq = np.einsum("ij,ij->i", delta, delta)  # квадрат расстояния
        dist_sq[used] = np.inf
        idx = int(np.argmin(dist_sq))
        order[k] = idx
        used[idx] = True
        current_end = strokes[idx][-1]
    return [strokes[i] for i in order]


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
