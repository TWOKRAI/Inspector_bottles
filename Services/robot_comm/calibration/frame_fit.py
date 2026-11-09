"""Подгонка системы координат по N >= 3 точкам: номинал в СК -> положение в базе (T5.4m).

Purpose:
    Чистая функция `fit_frame`: по парам «точка в базе / номинальная точка в СК» даёт три точки, задающие
    `FrameDef` (начало, точка на оси X, точка в плоскости XY), угол поворота вокруг Z и невязки. Файлов и
    робота не касается.

Public API: `FrameFit`, `fit_frame`, `MAX_RESIDUAL_MM`, `MIN_SECOND_SINGULAR_MM`, `FRAME_POINT_OFFSET_MM`,
    `MAX_COORD_MM`.

Stability: lite (контракт держат тесты `test_calibration_math.py`).

Потоков и состояния нет.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from Services.robot_comm.calibration.belt import (
    TEXT_FRAME_BAD_POINTS,
    TEXT_FRAME_DEGENERATE,
    TEXT_FRAME_RESIDUAL,
    TEXT_FRAME_UPSIDE_DOWN,
    CalibrationError,
)

__all__ = [
    "FRAME_POINT_OFFSET_MM",
    "MAX_COORD_MM",
    "MAX_RESIDUAL_MM",
    "MIN_SECOND_SINGULAR_MM",
    "FrameFit",
    "fit_frame",
]

# Допустимая наибольшая невязка подгонки, мм.
MAX_RESIDUAL_MM: float = 0.5
# Номинальные точки вырождены, если второе сингулярное число их центрированной матрицы меньше, мм.
MIN_SECOND_SINGULAR_MM: float = 1.0
# Наибольшая допустимая по модулю координата входной точки (база и номинал), мм. Физический предел рабочей зоны с
# запасом; без него координата ~1e155 и больше переполняет произведения матрицы `H` до inf, и `np.linalg.svd` зависает.
MAX_COORD_MM: float = 1e6
# Расстояние от начала СК до точек `on_x` и `in_plane` в локальных координатах, мм.
FRAME_POINT_OFFSET_MM: float = 100.0


@dataclass(frozen=True)
class FrameFit:
    """Результат подгонки СК.

    Поля (все числа — `float` Python): `origin` — начало СК в базе; `on_x` — точка локальной
    (`FRAME_POINT_OFFSET_MM`, 0, 0) в базе; `in_plane` — точка локальной (0, `FRAME_POINT_OFFSET_MM`, 0) в
    базе; `yaw_deg` — угол оси X СК к оси X базы вокруг Z, градусы; `residuals_mm` — невязка по каждой
    входной точке в порядке входа; `max_residual_mm` — наибольшая невязка. Три точки подходят в `FrameDef`.
    """

    origin: tuple[float, float, float]
    on_x: tuple[float, float, float]
    in_plane: tuple[float, float, float]
    yaw_deg: float
    residuals_mm: tuple[float, ...]
    max_residual_mm: float


def fit_frame(
    base: Sequence[tuple[float, float, float]],
    local: Sequence[tuple[float, float, float]],
    *,
    max_residual_mm: float = MAX_RESIDUAL_MM,
) -> FrameFit:
    """Подогнать СК по точкам: `base[i]` — положение в базе, `local[i]` — номинал той же точки в СК.

    Pre: `base` и `local` одной длины N >= 3, координаты (x, y, z) в мм, конечные; номинальные точки `local`
    не лежат на одной прямой.
    Post: `FrameFit` (поля — в его докстроке); СК правая, её ось Z смотрит вверх базы; масштаб не
    оценивается (СК — движение твёрдого тела).
    Raises: `CalibrationError` с текстом
        `TEXT_FRAME_BAD_POINTS` — длины не равны, N < 3, координата не конечна или больше `MAX_COORD_MM` по модулю;
        `TEXT_FRAME_DEGENERATE` — номинальные точки вырождены;
        `TEXT_FRAME_RESIDUAL` — наибольшая невязка больше `max_residual_mm`;
        `TEXT_FRAME_UPSIDE_DOWN` — ось Z подогнанной СК смотрит вниз базы.
    Порядок проверок — как в списке Raises.

    Алгоритм (T5.4m, 2a):
    1. Центроиды `lc`, `bc`; второе сингулярное число центрированной матрицы `local` меньше
       `MIN_SECOND_SINGULAR_MM` -> DEGENERATE (точки на одной прямой или в одной точке).
    2. Kabsch: `H = Σ (l - lc)(b - bc)^T`; `U, S, Vt = svd(H)`; `d = sign(det(Vt^T U^T))`;
       `R = Vt^T diag(1, 1, d) U^T`; `t = bc - R lc`. Поправка `d` обязательна: без неё зеркальный набор
       «подгоняется» отражением (`det R = -1`).
    3. Невязки `|R l_i + t - b_i|`; наибольшая больше `max_residual_mm` -> RESIDUAL. Эта проверка стоит ДО
       проверки «перевёрнута»: грубая ошибка в перевёрнутом наборе даёт невязку.
    4. Ось Z СК в базе `R (0, 0, 1)` с z < 0 -> UPSIDE_DOWN: `Frame.from_points` развернул бы нормаль, и
       сохранённая СК разошлась бы с подгонкой. Зеркальный набор (y x -1) - это поворот на 180 градусов
       вокруг оси листа: подгоняется точно, поэтому даёт UPSIDE_DOWN, а не RESIDUAL.
    5. `origin = t`, `on_x = R (100, 0, 0) + t`, `in_plane = R (0, 100, 0) + t`,
       `yaw_deg = atan2(R[1, 0], R[0, 0])` в градусах; все числа приводятся к `float` Python.

    Сила проверки невязки. При N = 3 у подгонки 6 степеней свободы на 9 уравнений, невязка почти пуста:
    сдвиг точки на 1 мм в плоскости листа даёт 0.336-0.656 мм (не всегда больше порога 0.5), сдвиг на 1-2 мм по Z
    - не более 0.008 мм (замер ревьюера стадии 0, не повторён). Ловятся грубые ошибки (перепутанная точка,
    сантиметры вместо миллиметров, сдвиг от 2 мм в плоскости). Как проверка подгонка осмысленна с N >= 4.
    """
    try:
        b_arr = np.array(base, dtype=float)
        l_arr = np.array(local, dtype=float)
    except (TypeError, ValueError) as exc:
        raise CalibrationError(TEXT_FRAME_BAD_POINTS) from exc
    if (
        b_arr.ndim != 2
        or b_arr.shape != l_arr.shape
        or b_arr.shape[1] != 3
        or b_arr.shape[0] < 3
        or not np.isfinite(b_arr).all()
        or not np.isfinite(l_arr).all()
        or np.abs(b_arr).max() > MAX_COORD_MM
        or np.abs(l_arr).max() > MAX_COORD_MM
    ):
        raise CalibrationError(TEXT_FRAME_BAD_POINTS)

    lc, bc = l_arr.mean(axis=0), b_arr.mean(axis=0)
    l_c, b_c = l_arr - lc, b_arr - bc
    if np.linalg.svd(l_c, compute_uv=False)[1] < MIN_SECOND_SINGULAR_MM:
        raise CalibrationError(TEXT_FRAME_DEGENERATE)

    h = l_c.T @ b_c
    u, _s, vt = np.linalg.svd(h)
    d = 1.0 if np.linalg.det(vt.T @ u.T) >= 0.0 else -1.0
    rot = vt.T @ np.diag([1.0, 1.0, d]) @ u.T
    shift = bc - rot @ lc

    residuals = np.linalg.norm(l_arr @ rot.T + shift - b_arr, axis=1)
    worst = float(residuals.max())
    if worst > max_residual_mm:
        raise CalibrationError(TEXT_FRAME_RESIDUAL)
    if rot[2, 2] < 0.0:
        raise CalibrationError(TEXT_FRAME_UPSIDE_DOWN)

    def _point(local_pt: tuple[float, float, float]) -> tuple[float, float, float]:
        v = rot @ np.array(local_pt) + shift
        return (float(v[0]), float(v[1]), float(v[2]))

    return FrameFit(
        origin=_point((0.0, 0.0, 0.0)),
        on_x=_point((FRAME_POINT_OFFSET_MM, 0.0, 0.0)),
        in_plane=_point((0.0, FRAME_POINT_OFFSET_MM, 0.0)),
        yaw_deg=float(math.degrees(math.atan2(rot[1, 0], rot[0, 0]))),
        residuals_mm=tuple(float(r) for r in residuals),
        max_residual_mm=worst,
    )
