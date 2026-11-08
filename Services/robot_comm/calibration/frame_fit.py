"""Подгонка системы координат по N >= 3 точкам: номинал в СК -> положение в базе (T5.4m).

Purpose:
    Чистая функция `fit_frame`: по парам «точка в базе / номинальная точка в СК» даёт три точки, задающие
    `FrameDef` (начало, точка на оси X, точка в плоскости XY), угол поворота вокруг Z и невязки. Файлов и
    робота не касается.

Public API: `FrameFit`, `fit_frame`, `MAX_RESIDUAL_MM`, `MIN_SECOND_SINGULAR_MM`, `FRAME_POINT_OFFSET_MM`.

Stability: lite (контракт держат тесты `test_calibration_math.py`).

Потоков и состояния нет.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

__all__ = [
    "FRAME_POINT_OFFSET_MM",
    "MAX_RESIDUAL_MM",
    "MIN_SECOND_SINGULAR_MM",
    "FrameFit",
    "fit_frame",
]

# Допустимая наибольшая невязка подгонки, мм.
MAX_RESIDUAL_MM: float = 0.5
# Номинальные точки вырождены, если второе сингулярное число их центрированной матрицы меньше, мм.
MIN_SECOND_SINGULAR_MM: float = 1.0
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
        `TEXT_FRAME_BAD_POINTS` — длины не равны, N < 3 или координата не конечна;
        `TEXT_FRAME_DEGENERATE` — номинальные точки вырождены;
        `TEXT_FRAME_RESIDUAL` — наибольшая невязка больше `max_residual_mm`;
        `TEXT_FRAME_UPSIDE_DOWN` — ось Z подогнанной СК смотрит вниз базы.
    Порядок проверок — как в списке Raises.
    """
    raise NotImplementedError
